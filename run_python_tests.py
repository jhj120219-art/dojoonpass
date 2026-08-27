"""파이썬 회귀 테스트 일괄 실행기 — 2026-08-17 Sprint 146 신설.

## 왜 이게 생겼나

이 저장소에는 `test_*.py` 가 37개 있는데 **한꺼번에 돌리는 수단이 없었다.**
`package.json` 에는 프런트용 `test:frontend` 만 있고, `.bat`/CI 어디에도 파이썬
테스트를 도는 것이 없다(2026-08-17 실측: `.github/workflows` 없음, `.bat`/`.ps1`
에서 `test_*.py` 참조 0건). 그래서 세션마다 셸 반복문을 즉석에서 만들어 썼고,
그 즉석 반복문이 **두 번 연속 결과를 잘못 읽었다.**

    1) `python $f | tail -3` 에 실패 문구가 없으면 통과로 셌다
       -> 마지막 3줄 위에서 죽은 실패를 놓친다.

    2) 파일 개수를 세어 "36 PASS / 1 FAIL" 이라고 보고했다
       -> 그중 4개는 **아무것도 단언하지 않고 0으로 끝나는 파일**이었다.
          `test_db.py` / `test_docs.py` / `test_docs2.py` 는 `ALLOW_LIVE_CRAWL=1`
          없이는 스스로 SKIP 하는 실크롤 스크립트고, `test_filter.py` 는 판정문 자체가
          없는 진단 스크립트다. 넷 다 "통과"로 집계됐다.

즉 문제는 테스트가 아니라 **집계**였다. 이 실행기는 그 집계를 정직하게 만든다.

## 판정 기준 — 종료코드를 1순위로 쓴다

실측으로 확인했다(2026-08-17): 실제 회귀 테스트 33개는 **전부** 실패 시 non-zero 로
끝난다(`sys.exit(1 if FAIL else 0)` 또는 `sys.exit(1)`). 실패를 주입해 본 결과
`test_auth_jwt.py` 도 1을 돌려준다. 그래서 종료코드는 믿을 수 있다.

반면 **출력 문구는 믿을 수 없다.** 이 저장소는 결과 어휘가 세 벌이다:

    [PASS]/[FAIL]        28개 파일
    [OK]/[NG]            일부
    "ALL ... TESTS PASSED" 만 있고 마커가 없는 파일  5개

게다가 `[FAIL]` 이 **테스트 대상의 정상 출력**인 경우가 있다 —
`test_auction_identity.py` 는 검증을 일부러 깨뜨려 `migrate_execute` 가 실패를
보고하는지 확인하므로, 통과할 때도 `[FAIL] document_status 불일치` 를 찍는다.
문구만 grep 하면 **통과한 테스트를 실패로 읽는다.**

    -> 그래서: 합격/불합격은 **종료코드**로, 판정문 유무는 **분류**에만 쓴다.

## 네 가지 상태로 나눈다 (통과와 무판정을 절대 합치지 않는다)

    PASSED      종료코드 0 + 판정문이 있다        진짜 통과
    FAILED      종료코드 != 0                     진짜 실패
    SKIPPED     스스로 건너뛴다고 밝힌 파일       실행 안 됨 (통과 아님)
    NO-VERDICT  0으로 끝났지만 판정문이 없다      검증했다고 말할 수 없음

`SKIPPED` 와 `NO-VERDICT` 를 요약에서 **따로** 찍는 이유는, 이것들이 통과 숫자에
섞여 들어간 것이 애초에 이 파일을 만든 이유이기 때문이다.

## 사용법

    python run_python_tests.py              # 전부
    python run_python_tests.py -k search    # 이름에 search 가 든 것만
    python run_python_tests.py -v           # 실패 파일의 출력도 함께

종료코드: 실패가 하나라도 있으면 1, 아니면 0. (SKIPPED/NO-VERDICT 는 0을 유지한다 —
이것들은 "깨졌다"가 아니라 "실행되지 않았다"이므로 게이트를 붉게 만들지 않는다.
대신 요약에 항상 눈에 띄게 남는다.)

이 파일은 **프로덕션 코드를 건드리지 않는다.** 순수 실행기다.
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))

# 파일이 "스스로 건너뛴다"고 밝히는 신호. 실크롤/유료 경로를 막아 둔 스크립트들이다.
SKIP_MARKERS = ("[SKIPPED]", "ALLOW_LIVE_CRAWL")

# "판정을 내렸다"고 인정하는 문구. 어휘가 세 벌이라 전부 받아 준다.
VERDICT_PATTERNS = (
    r"\[PASS\]", r"\[FAIL\]", r"\[OK\]", r"\[NG\]",
    r"ALL .*(TESTS?|PASSED)", r"\bFAILED\s*\(", r"결과:\s*\d+\s*PASS",
)

# 파일 하나당 상한. 통합 테스트(TestClient 부팅, 임시 DB 복사)가 있어 넉넉히 준다.
PER_FILE_TIMEOUT = 900


# ---------------------------------------------------------------------------
# 운영 DB 감시 (2026-08-25 신설)
#
# 왜 — 이 실행기를 한 번 돌린 전후로 운영 `auction.db` 의 md5 가 바뀌고 있었다.
# 파일별로 격리해 재니 5개가 `get_connection()` 으로 **운영 DB 에 직접** 합성 행을
# 심고 있었다(test_api_regression / test_beta_journey / test_doc_storage_atomicity /
# test_race_conditions / test_subscription_policy). 끝에 지우므로 행수는 원복돼서
# **아무도 몰랐다** — `sqlite_sequence` 만 영구히 전진했고, 중간에 죽으면 합성 행이
# 그대로 남았다. 다섯 파일은 `qa_scratch_db.activate()` 로 고쳤지만, 고친 것보다
# **다시 생기지 않게 하는 것**이 중요하다. 새 테스트 파일은 계속 추가된다.
#
# 그래서 허용목록(누가 무엇을 import 했는가)이 아니라 **행동**을 본다 — 파일 하나를
# 돌릴 때마다 운영 DB 파일의 지문을 재고, 달라지면 그 파일을 지목하고 게이트를
# 붉게 만든다. 허용목록은 새 파일을 놓치지만 이건 놓치지 않는다.
#
# 비용 (2026-08-28 재측정 — 이 줄은 원래 "5MB md5 가 파일당 ~10ms, 전체 ~0.6s" 였다):
#
#     감시 대상 합계   15.59 MB   (auction.db 7.04 + 로그 5개 8.55)
#     지문 1회         19.6 ms
#     스위트 1회       72파일 x 2(전/후) = **2.8초 / 2.19 GB 해싱**
#
# 여전히 스위트(약 116초)의 2~3% 라 감수할 만하다. 다만 **이 비용은 로그를 따라
# 자란다** — 이 저장소에는 **로그 로테이션이 한 군데도 없다**(전수 확인:
# RotatingFileHandler/maxBytes/backupCount 참조 0건). 증가 속도 실측:
#
#     logs/scraper.log     약 1,000줄/일 (~85KB/일)   현재 4.05 MB
#     logs/daily_run.log   약 1,000줄/일             현재 3.01 MB
#     logs/doc_run.log     약 2,400~3,300줄/일       현재 1.31 MB  <- 워커가 매일 돌기 시작
#
# 1년이면 감시 대상이 약 40MB, 스위트당 약 7초 / 5.6GB 가 된다. 그때는 이 방식을
# 다시 봐야 한다(크기+mtime 선비교 등). **로테이션 도입은 옛 로그를 지우는 일이라
# 승인 영역**이므로 여기서는 숫자만 정직하게 남긴다 — docs/BUGS.md #269.
# ---------------------------------------------------------------------------
def live_db_path():
    """감시 대상 = 제품이 실제로 여는 경로. 이름으로 고르지 않는다 —
    저장소 루트에는 `auction.db.backup_*` 가 16개 더 있다."""
    try:
        sys.path.insert(0, ROOT)
        import storage.database as dbmod
        return dbmod.DB_PATH
    except Exception:
        return os.path.join(ROOT, "auction.db")


# ---------------------------------------------------------------------------
# 감시 대상을 운영 로그까지 넓힌다 (2026-08-25, docs/BUGS.md #192)
#
# 왜 — 위 감시가 DB 축을 닫자마자 **같은 사고가 파일 축에 그대로 남아 있는 것**을
# 찾았다. `collect_documents.py` / `mvp_scraper.py` 가 import 시점에 루트 로거에
# FileHandler 를 붙여서, 그 모듈을 import 하는 테스트가 돌 때마다 합성 로그가
# 운영 로그에 섞였다. 실측(2026-08-25):
#
#     logs/doc_collect.log   4,136줄 중 1,651줄(40%)이 QA 산출물
#     logs/scraper.log      36,420줄 중 08-24~25 자 2,346줄이 QA 산출물
#
# 마지막 실제 크롤은 2026-08-12 다. 즉 이 로그만 읽으면 "오늘 돌았고 전 법원이
# 실패했다"로 보인다 — 이 저장소가 9일간 크롤 중단을 몰랐던 그 거짓 증거와
# 같은 계열이다. 이름만 다를 뿐 DB 사고와 같은 결함이므로 감시도 같은 방식으로 한다.
#
# 목록을 `logs/` 전체로 두지 않는 이유: 그 폴더에는 세션 산출물(s2xx_*.log)이
# 섮여 있어 감시가 소음만 낸다. **이 저장소가 증거로 쓰는 파일**만 골랐다 —
# 네 개 다 `audit_schedule_health.py` / `check_pipeline2.py` / `check_morning.py` 가
# "마지막으로 언제 돌았는가"를 판단하는 데 직접 읽는다.
# ---------------------------------------------------------------------------
WATCHED_LOGS = (
    "logs/daily_run.log",       # audit_schedule_health.py: run_daily.bat 흔적
    "logs/doc_run.log",         # audit_schedule_health.py: run_doc_worker.bat 흔적
    "logs/scraper.log",         # mvp_scraper.py 운영 로그
    "logs/doc_collect.log",     # collect_documents.py 운영 로그
    "logs/migrate_execute.log", # run_daily.bat 2단계 흔적
)


def watched_paths():
    """(표시이름, 절대경로) 목록. 운영 DB + 운영 로그."""
    paths = [("auction.db", live_db_path())]
    paths += [(rel, os.path.join(ROOT, *rel.split("/"))) for rel in WATCHED_LOGS]
    return paths


def fingerprint_all(paths):
    return {label: db_fingerprint(path) for label, path in paths}


def db_fingerprint(path):
    """없으면 None. '없다'와 '비었다'를 구별하기 위해 크기도 함께 넣는다."""
    try:
        h = hashlib.md5()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return "%d:%s" % (os.path.getsize(path), h.hexdigest())
    except OSError:
        return None


# OneDrive 충돌 사본 — **제품 검사가 아니다** (2026-08-27, docs/BUGS.md #253/#258)
#
# `<이름>-DESKTOP-XXXX.py` 는 OneDrive 가 두 대에서 같은 파일이 바뀐 것을 보고 만든
# 사본이고, 실수로 커밋되어 8개가 추적되고 있다. 내용은 제품 파일의 **옛 판본**이다.
#
# 이것들을 같이 돌리면 게이트가 세 가지로 망가진다(2026-08-27 실측):
#
#     test_crawl_orchestration-DESKTOP-DVRJEGP.py   FAILED (KeyError: 'unchanged')
#                                                   -> upsert 계약이 생기기 전 판본이다
#     test_audit_selftests-DESKTOP-DVRJEGP.py       FAILED, **605초**(파일당 상한에 걸림)
#                                                   -> 스위트 전체가 2분에서 12분이 된다
#     그리고 이 둘은 **고칠 수 없다** — 충돌 사본 정리는 사람이 어느 쪽이 최신인지
#     골라야 하는 일이라 자동으로 손대지 않는다.
#
# 영구히 붉은 게이트에서는 **새 회귀와 이미 아는 부채를 구별할 수 없다.** 그것이
# 애초에 이 실행기를 만든 이유(통과와 무판정을 합치지 않는다)와 정확히 같은 문제다.
#
# ★ 그래서 숨기지 않고 **따로 센다.** 실행하지 않되 요약에 전용 칸으로 남기고,
#   `--include-conflicts` 로 언제든 돌려 볼 수 있다. 개수는
#   `test_schema_hygiene.py` 가 따로 감시해 **늘어나면 붉어진다.**
CONFLICT_COPY_RE = re.compile(r"-DESKTOP-[A-Z0-9]+(?:[.][A-Za-z0-9]+)?$")


def is_conflict_copy(name):
    return bool(CONFLICT_COPY_RE.search(name))


def discover(pattern=None, include_conflicts=False):
    """실행할 테스트 파일 **목록**을 돌려준다.

    ★ 반환값은 예나 지금이나 **리스트 하나**다. 충돌 사본 목록이 필요해졌을 때
      튜플로 바꿀 뻔했는데, `test_runner_contract.py` 가 `set(R.discover())` 로
      이 계약을 붙잡고 있었다(그리고 곧바로 붉어졌다). 계약을 바꾸는 대신
      `conflict_copies()` 를 따로 뒀다 — 그 검사가 하려던 일이 정확히 이것이다.
    """
    names = sorted(
        f for f in os.listdir(ROOT)
        if f.startswith("test_") and f.endswith(".py")
        and os.path.isfile(os.path.join(ROOT, f))
    )
    if pattern:
        names = [f for f in names if pattern.lower() in f.lower()]
    if not include_conflicts:
        names = [f for f in names if not is_conflict_copy(f)]
    return names


def conflict_copies(pattern=None):
    """실행 대상에서 뺀 OneDrive 충돌 사본 목록(요약에만 쓴다)."""
    names = sorted(
        f for f in os.listdir(ROOT)
        if f.startswith("test_") and f.endswith(".py")
        and os.path.isfile(os.path.join(ROOT, f)) and is_conflict_copy(f)
    )
    if pattern:
        names = [f for f in names if pattern.lower() in f.lower()]
    return names


def classify(returncode, out):
    """(상태, 단언수) 를 돌려준다. 상태 판단의 1순위는 종료코드다."""
    n_pass = len(re.findall(r"\[PASS\]|\[OK\]", out))
    n_fail = len(re.findall(r"\[FAIL\]|\[NG\]", out))
    asserts = n_pass + n_fail

    if returncode is None:
        return "TIMEOUT", asserts
    if returncode != 0:
        return "FAILED", asserts
    # 여기부터는 종료코드 0 — 그래도 "통과"라고 부르려면 판정문이 있어야 한다.
    if any(m in out for m in SKIP_MARKERS) and asserts == 0:
        return "SKIPPED", asserts
    if any(re.search(p, out) for p in VERDICT_PATTERNS):
        return "PASSED", asserts
    return "NO-VERDICT", asserts


# 실패한 파일에서 곧바로 보여 줄 마지막 줄 수. 스크롤을 덮지 않으면서
# 원인 한 줄(대개 traceback 마지막 줄)은 들어가는 크기다.
FAIL_TAIL_LINES = 12


def run_one(name):
    started = time.time()
    try:
        p = subprocess.run(
            [sys.executable, name], cwd=ROOT,
            capture_output=True, timeout=PER_FILE_TIMEOUT,
        )
        rc = p.returncode
        out = (p.stdout + p.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        rc = None
        got = (exc.stdout or b"") + (exc.stderr or b"")
        out = got.decode("utf-8", "replace")
    status, asserts = classify(rc, out)
    return status, asserts, out, rc, time.time() - started


def emit(line):
    """콘솔 코드페이지가 cp949 여도 죽지 않게 찍는다.

    이 저장소는 한글 출력이 기본이고 Windows 기본 콘솔은 cp949 다.
    `test_console_encoding.py` 가 지키는 것과 같은 문제로, 여기서 죽으면
    실행기 자체가 결과를 못 보여 준다.
    """
    try:
        print(line)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(line.encode(enc, "replace").decode(enc, "replace"))


def main():
    ap = argparse.ArgumentParser(description="파이썬 회귀 테스트 일괄 실행")
    ap.add_argument("-k", "--filter", dest="pattern", default=None,
                    help="파일명 부분 일치 필터")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="실패한 파일의 출력을 함께 보여 준다")
    ap.add_argument("--include-conflicts", action="store_true",
                    help="OneDrive 충돌 사본(-DESKTOP-*.py)도 함께 실행한다"
                         " (기본값: 실행하지 않고 요약에만 남긴다, BUGS #253)")
    args = ap.parse_args()

    files = discover(args.pattern, args.include_conflicts)
    skipped_conflicts = ([] if args.include_conflicts
                         else conflict_copies(args.pattern))
    if not files:
        emit("대상 파일이 없습니다.")
        return 0

    emit("=" * 72)
    emit(" 파이썬 회귀 테스트 %d개 실행" % len(files))
    emit("=" * 72)

    buckets = {"PASSED": [], "FAILED": [], "SKIPPED": [], "NO-VERDICT": [], "TIMEOUT": []}
    outputs = {}
    total_asserts = 0
    t0 = time.time()

    exitcodes = {}
    watched = watched_paths()
    live_db = watched[0][1]
    # {파일명: [바뀐 대상 표시이름, ...]} — DB 만 보던 것을 운영 산출물 전체로 넓혔다 (#192)
    touched = {}
    for i, name in enumerate(files, 1):
        before = fingerprint_all(watched)
        status, asserts, out, rc, secs = run_one(name)
        after = fingerprint_all(watched)
        changed = [label for label, _ in watched if before[label] != after[label]]
        if changed:
            touched[name] = changed
        buckets[status].append(name)
        outputs[name] = out
        exitcodes[name] = rc
        total_asserts += asserts
        emit("[%2d/%2d] %-11s %-38s 단언%-5d %5.1fs" %
             (i, len(files), status, name, asserts, secs))
        for label in changed:
            emit("        ** 운영 산출물을 변경했다 ** %s" % label)
            emit("        전: %s" % before[label])
            emit("        후: %s" % after[label])

        # ---------------------------------------------------------------
        # 실패는 **그 자리에서** 증거를 남긴다 (2026-08-18 Sprint 203).
        #
        # 예전에는 실패 출력이 `-v` 를 줬을 때만 나왔다. 그런데 실패를 발견하는
        # 순간은 대개 `-v` 없이 돌린 순간이고, 다시 돌리면 통과하는 간헐 실패는
        # **그 한 번이 유일한 기회**다. 실제로 이 자리에서 한 번 놓쳤다 -
        # `test_doc_storage_atomicity.py` 가 0.1초 만에 25단언에서 죽었는데,
        # 재현하려고 4번 더 돌렸을 때는 전부 통과해서 원인을 볼 수 없었다.
        #
        # 이 저장소가 이미 배운 것과 같은 교훈이다(로그에 안 남아 9일간 크롤
        # 중단을 몰랐던 일). 실패했는데 아무 흔적이 없으면 실패하지 않은 것과
        # 구별되지 않는다.
        # ---------------------------------------------------------------
        if status in ("FAILED", "TIMEOUT") and not args.verbose:
            tail = [ln for ln in out.splitlines() if ln.strip()][-FAIL_TAIL_LINES:]
            emit("        (종료코드 %s - 마지막 %d줄, 전체는 -v)"
                 % (rc, len(tail)))
            for ln in tail:
                emit("        | " + ln[:200])

    emit("=" * 72)
    emit(" 통과 %d | 실패 %d | 건너뜀 %d | 판정없음 %d | 시간초과 %d   (단언 %d건, %.1fs)"
         % (len(buckets["PASSED"]), len(buckets["FAILED"]), len(buckets["SKIPPED"]),
            len(buckets["NO-VERDICT"]), len(buckets["TIMEOUT"]),
            total_asserts, time.time() - t0))
    emit("=" * 72)

    # 통과가 아닌 것은 전부 이름을 남긴다 — 요약 숫자만 보고 넘어가지 못하게 한다.
    for label, key in (("실패", "FAILED"), ("시간초과", "TIMEOUT"),
                       ("건너뜀(실행되지 않음 — 통과가 아니다)", "SKIPPED"),
                       ("판정문 없음(검증했다고 말할 수 없다)", "NO-VERDICT")):
        if buckets[key]:
            emit("\n%s (%d):" % (label, len(buckets[key])))
            for n in buckets[key]:
                emit("   - %s" % n)

    if skipped_conflicts:
        emit("")
        emit("OneDrive 충돌 사본 %d개 - **실행하지 않았다**(제품 검사가 아니다, BUGS #253):"
             % len(skipped_conflicts))
        for n in skipped_conflicts:
            emit("   - %s" % n)
        emit("   정리는 사람이 한다(어느 쪽이 최신인지 골라야 한다)."
             " 돌려 보려면 --include-conflicts.")

    if touched:
        emit("")
        emit("운영 산출물을 변경한 파일 (%d) - 통과 여부와 무관하게 게이트를 붉게 만든다:" % len(touched))
        for n in sorted(touched):
            emit("   - %-38s -> %s" % (n, ", ".join(touched[n])))
        emit("")
        emit("   [로그를 바꿔 놓은 경우] 그 파일이 import 한 모듈이 루트 로거에 FileHandler 를")
        emit("   붙였다는 뜻이다. 운영 파일 로그는 `if __name__ == \"__main__\":` 안에서만")
        emit("   붙인다 - 예제: mvp_scraper.attach_file_log() / collect_documents.attach_file_log()")
        emit("   경위와 이유: docs/BUGS.md #192")
        emit("")
        emit("   [DB 를 바꿨 경우] 대상: %s" % live_db)
        emit("   고치는 법: 그 파일의 `sys.path.insert(...)` 바로 다음, `storage.database` /")
        emit("   `api_server` 를 import 하기 **전**에 임시 사본으로 돌린다:")
        emit("       import storage.database as _qa_dbmod")
        emit("       _qa_tmp = tempfile.mkdtemp(prefix=\"dojoonpass-qa-\")")
        emit("       shutil.copy2(_qa_dbmod.DB_PATH, os.path.join(_qa_tmp, \"auction.db\"))")
        emit("       _qa_dbmod.DB_PATH = os.path.join(_qa_tmp, \"auction.db\")")
        emit("   예제: test_subscription_policy.py / test_admin_failure_injection.py")
        emit("   경위와 이유: docs/BUGS.md #186")

    if args.verbose:
        for n in buckets["FAILED"] + buckets["TIMEOUT"]:
            emit("\n" + "-" * 72)
            emit("### %s 출력" % n)
            emit("-" * 72)
            emit(outputs[n][-4000:])

    return 1 if (buckets["FAILED"] or buckets["TIMEOUT"] or touched) else 0


if __name__ == "__main__":
    sys.exit(main())
