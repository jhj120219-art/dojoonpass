# -*- coding: utf-8 -*-
"""
예약 실행이 **실제로 무언가를 했는지** 대조하는 읽기 전용 감사기 (2026-08-18 Sprint 204).

왜 만들었나
---------------------------------------------------------------------------
이 저장소는 같은 착각을 두 번 했다.

    Sprint 187   `Get-ScheduledTask` 에서 `DOJOONPASS_DAILY`(run_daily.bat, 매일 03:00,
                 LastTaskResult 0)를 보고 "물건 수집은 정상 동작 중"이라고 기록했다.
    Sprint 180+  실제로는 `logs/daily_run.log` 가 2026-08-11 이후 갱신된 적이 없고
                 `auction_item.crawl_date` 최신값이 2026-08-12(단발 9건)였다.

작업 스케줄러가 "성공(0)"이라고 말하는 것은 **프로세스가 0으로 끝났다**는 뜻이지
이 저장소에 무엇이 쌓였다는 뜻이 아니다. 다른 사본을 가리켰을 수도, 즉시 종료했을
수도 있다. 그 둘을 구분하려면 **작업 상태와 결과물을 함께 봐야** 한다.

이 감사기는 세 축을 따로 재고 **서로 어긋나는 지점을 지목한다.**

    [1] 등록      스케줄러에 이 저장소를 가리키는 작업이 있는가
    [2] 실행      그 작업이 마지막으로 언제 돌았고 무엇을 반환했는가
    [3] 효과      로그 마커 / DB 수집일 / 큐 소진이 그 시각 이후에 움직였는가

무엇을 하지 않는가
---------------------------------------------------------------------------
아무것도 바꾸지 않는다. 등록하지도, 지우지도, DB 를 쓰지도 않는다.
등록은 운영 환경 변경이라 승인 영역이고, 이 파일은 그 판단에 쓸 사실만 모은다.

    python audit_schedule_health.py
    python audit_schedule_health.py --selftest    # 모순 탐지기가 실제로 우는지 확인
"""
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))

# 등록 스크립트가 만드는 작업 이름과, 그 작업이 남겨야 할 로그.
# 이름을 여기 박아 두지 않는다 - register_scheduler_tasks.ps1 에서 읽는다.
# (하드코딩한 목록은 스크립트가 바뀌면 조용히 어긋난다.)
REGISTER_SCRIPT = "register_scheduler_tasks.ps1"

LOG_OF_BAT = {
    "run_daily.bat": "logs/daily_run.log",
    "run_doc_worker.bat": "logs/doc_run.log",
    "run_priority_refresh.bat": "logs/doc_run.log",
}

# 작업이 "성공"이라고 말한 뒤 이 시간 안에 저장소에 흔적이 없으면 모순으로 본다.
# 가장 긴 배치(전체 크롤 실측 3.1시간)에 여유를 얹은 값이다.
EFFECT_WINDOW_HOURS = 8


def db_path():
    """실행 시점의 값을 읽는다(모듈 로드 시 스냅샷을 뜨면 selftest 가 못 바꾼다)."""
    try:
        import storage.database as dbmod
        return getattr(dbmod, "DB_PATH", os.path.join(ROOT, "auction.db"))
    except Exception:
        return os.path.join(ROOT, "auction.db")


def expected_tasks():
    """등록 스크립트에서 (작업이름, 배치파일, 시각)을 뽑는다.

    못 읽으면 **빈 목록을 돌려주지 않고 예외를 낸다** - 조용히 0건을 감사하고
    초록으로 끝나는 것이 이 저장소가 반복해서 당한 함정이다.
    """
    import re
    path = os.path.join(ROOT, REGISTER_SCRIPT)
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        text = fh.read()
    found = re.findall(
        r"Name\s*=\s*'([^']+)'\s*;\s*Bat\s*=\s*'([^']+)'\s*;\s*Time\s*=\s*'([^']+)'",
        text)
    if not found:
        raise RuntimeError(
            "%s 에서 작업 정의를 하나도 못 읽었다. 형식이 바뀌었는지 확인할 것." % REGISTER_SCRIPT)
    return found


def query_tasks():
    """schtasks 로 전체 작업을 읽어 (이름 -> 정보) 로 돌려준다.

    PowerShell 이 아니라 schtasks 를 쓰는 이유: 인코딩/실행정책에 덜 휘둘린다.
    실패하면 빈 dict 가 아니라 None 을 돌려준다 - "작업이 없다"와
    "조회를 못 했다"를 절대 섞지 않는다.
    """
    try:
        p = subprocess.run(["schtasks", "/query", "/fo", "csv", "/v"],
                           capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    text = (p.stdout or b"").decode("cp949", "replace")
    return parse_schtasks_csv(text)


# 마지막 파싱에서 **버린 행**을 남긴다. 버림은 조용하면 안 된다 —
# 버려진 행 하나가 곧 "감사에서 사라진 작업 하나"다.
PARSE_STATS = {"column_mismatch": 0, "before_header": 0}


def parse_schtasks_csv(text):
    """schtasks /fo csv /v 출력을 (작업이름 -> 레코드) 로 만든다.

    파싱을 따로 뗀 이유: selftest 가 실제 스케줄러 없이 이 규칙을 검증할 수 있어야
    한다. 이 함수가 한 번 틀려서 249개를 0개로 읽었다(Sprint 204).
    """
    import csv
    import io as _io
    PARSE_STATS["column_mismatch"] = 0
    PARSE_STATS["before_header"] = 0
    rows = list(csv.reader(_io.StringIO(text)))
    if not rows:
        return None
    # ★ 헤더는 **첫 칸이 아니다.** `/v` 출력의 1번 칸은 "호스트 이름"이고
    #   작업 이름은 2번 칸이다. 처음에 첫 칸만 보고 판정했다가 249개를 0개로
    #   읽었다(2026-08-18 Sprint 204에 실측으로 잡음). 이름이 **어느 칸에 있든**
    #   찾도록 행 전체에서 고른다.
    NAME_KEYS = ("TaskName", "작업 이름")
    header = None
    out = {}
    for r in rows:
        if not r:
            continue
        cells = [c.strip('"') for c in r]
        if any(k in cells for k in NAME_KEYS):
            header = cells
            continue
        if header is None:
            PARSE_STATS["before_header"] += 1
            continue
        if len(r) != len(header):
            # ★ 칸 수가 다른 행을 **조용히 버리지 않는다** (2026-08-19 Sprint 217).
            #   버리면 그 작업은 감사에서 통째로 사라지고 결과는 "그런 작업 없음"이라는
            #   **정상과 똑같은 모양**으로 나온다. 이 감사기가 존재하는 이유가
            #   바로 그 착각(등록됐는데 0개로 읽음)이었다.
            PARSE_STATS["column_mismatch"] += 1
            continue
        rec = dict(zip(header, cells))
        name = ""
        for k in NAME_KEYS:
            if rec.get(k):
                name = rec[k]
                break
        if name:
            out[name.strip()] = rec

    # ★ 읽을 것이 있었는데 하나도 못 뽑았으면 "0개"가 아니라 **조회 실패**다.
    #   이 둘을 섞는 순간 이 감사기는 자기가 막으려던 착각을 스스로 저지른다.
    if rows and not out:
        return None
    return out


def _get(rec, *names):
    for n in names:
        if n in rec and rec[n] not in ("", "N/A"):
            return rec[n]
    return ""


def repo_pointing_tasks(tasks):
    """이 저장소를 가리키는 작업만 고른다. 이름이 아니라 **실행 내용**으로 고른다.

    Sprint 187 의 `DOJOONPASS_DAILY` 처럼 등록 스크립트가 모르는 이름으로
    등록돼 있을 수 있다. 이름으로 찾으면 그런 것을 통째로 놓친다.
    """
    hits = {}
    root_l = ROOT.lower()
    for name, rec in tasks.items():
        blob = " ".join([
            _get(rec, "Task To Run", "실행할 작업"),
            _get(rec, "Start In", "시작 위치"),
        ]).lower()
        if root_l in blob or any(b.lower() in blob for b in LOG_OF_BAT):
            hits[name] = rec
    return hits


def log_state(rel):
    """로그 파일의 마지막 갱신 시각과 마지막 결과 마커를 돌려준다."""
    path = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.isfile(path):
        return {"exists": False, "mtime": None, "marker": None}
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    marker = None
    last_line = None
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 20000))
            tail = fh.read().decode("utf-8", "replace")
        for line in reversed(tail.splitlines()):
            if line.strip() and last_line is None:
                last_line = line.strip()
            if "[SUCCESS]" in line or "[FAILED]" in line:
                marker = line.strip()
                break
    except OSError:
        pass
    # 마커가 없는 것도 사실이다. `logs/daily_run.log` 는 Sprint 13/54 이전 형식이라
    # `Finished at ...` 만 있고 [SUCCESS] 가 없다 - 그때는 마지막 줄을 대신 보여 준다
    # (아무것도 안 보여 주면 "로그가 비었다"로 오해한다).
    return {"exists": True, "mtime": mtime, "marker": marker, "last_line": last_line}


def db_state():
    path = db_path()
    if not os.path.exists(path):
        return None
    con = sqlite3.connect("file:" + path.replace("\\", "/") + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        st = {}
        st["crawl_date_max"] = con.execute(
            "SELECT MAX(crawl_date) FROM auction_item").fetchone()[0]
        today = datetime.today().strftime("%Y-%m-%d")
        st["future_items"] = con.execute(
            "SELECT COUNT(*) FROM auction_item WHERE auction_date >= ?", (today,)).fetchone()[0]
        st["last_auction_date"] = con.execute(
            "SELECT MAX(auction_date) FROM auction_item").fetchone()[0]
        st["queue"] = {r[0]: r[1] for r in con.execute(
            "SELECT status, COUNT(*) FROM document_queue GROUP BY status")}
        try:
            st["doc_raw"] = con.execute("SELECT COUNT(*) FROM doc_raw").fetchone()[0]
        except sqlite3.Error:
            st["doc_raw"] = None
        # ★ 2026-08-25 추가 - "등록 0개"는 이미 알려져 있었지만, 그것이 실제로
        #   큐에 어떤 결과를 남기는지는 이 감사기가 재지 않았다. `enqueued_at`(크롤이
        #   매일 새로 쌓는 값)과 `last_attempt_at`(DocWorker 가 그 행을 만졌을 때만
        #   찍는 값)의 최댓값을 나란히 재면 "쌓이기만 하고 안 빠진다"를 직접 보여줄
        #   수 있다 - 실측(2026-08-24)으로 이 값이 6주 넘게 벌어져 있는 것을 확인했다.
        st["queue_enqueued_max"] = con.execute(
            "SELECT MAX(enqueued_at) FROM document_queue").fetchone()[0]
        st["queue_last_attempt_max"] = con.execute(
            "SELECT MAX(last_attempt_at) FROM document_queue"
            " WHERE last_attempt_at IS NOT NULL").fetchone()[0]
        row = con.execute(
            "SELECT COUNT(*), SUM(CASE WHEN auction_date < ? AND TRIM(auction_date) <> ''"
            " THEN 1 ELSE 0 END) FROM document_queue WHERE status='pending'",
            (today,)).fetchone()
        st["queue_pending_total"] = row[0] or 0
        st["queue_pending_moot"] = row[1] or 0
        return st
    finally:
        con.close()


def _parse_last_run(text):
    """schtasks 의 '마지막 실행 시간'을 관대하게 읽는다. 못 읽으면 None."""
    if not text:
        return None
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%m/%d/%Y %I:%M:%S %p",
                "%Y-%m-%d %p %I:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def contradictions(hits, logs, db):
    """작업 상태와 결과물이 어긋나는 지점을 찾는다. 이 함수가 이 파일의 핵심이다."""
    out = []
    for name, rec in hits.items():
        result = _get(rec, "Last Result", "마지막 결과")
        last = _parse_last_run(_get(rec, "Last Run Time", "마지막 실행 시간"))
        if last is None:
            continue
        if str(result).strip() not in ("0", "0x0"):
            continue
        # 성공이라고 말했다. 그 시각 이후에 이 저장소가 움직였는가?
        moved = False
        for rel, state in logs.items():
            if state["mtime"] and state["mtime"] >= last - timedelta(minutes=5):
                moved = True
                break
        if not moved:
            newest = max([s["mtime"] for s in logs.values() if s["mtime"]] or [None])
            out.append(
                "작업 '%s' 는 %s 에 성공(0)으로 끝났다고 하는데, 이 저장소의 로그는 "
                "%s 이후 갱신된 적이 없다. 다른 사본을 가리키거나 즉시 종료했을 수 있다."
                % (name, last.strftime("%Y-%m-%d %H:%M"),
                   newest.strftime("%Y-%m-%d %H:%M") if newest else "(로그 없음)"))
    return out


# 큐가 "쌓이기만 하고 안 빠지는" 상태를 판정하는 문턱. `run_daily.bat`(크롤)는
# 매일 돌지만 doc_worker 는 별도 등록이라 없어도 되는 값이라, 하루 이틀의 자연스러운
# 지연과 "몇 주째 정지"를 가르는 여유를 넉넉히 둔다.
QUEUE_STALL_DAYS = 3


def _parse_db_ts(text):
    """`document_queue.enqueued_at`/`last_attempt_at` 은 `datetime.isoformat()`로
    쓰인다(`storage/database.py`) - schtasks 출력과 형식이 다르므로 `_parse_last_run`
    (schtasks 전용)을 재사용하지 않고 따로 둔다. 못 읽으면 None(추측하지 않는다)."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.strip())
    except ValueError:
        return None


def queue_stall_signal(db):
    """`queue_enqueued_max`(크롤이 쌓은 최신 시각) 대비 `queue_last_attempt_max`
    (DocWorker 가 마지막으로 큐를 만진 시각)가 `QUEUE_STALL_DAYS` 이상 뒤처지면
    지목한다. 순수 함수라 selftest 가 스케줄러/DB 없이도 이 판정을 검증할 수 있다.

    ★ 두 값 중 하나라도 없으면(파싱 실패 포함) 판정하지 않는다 - "모른다"를
      "정상"으로 읽지 않는다(이 파일 전체의 원칙, `contradictions()`와 동일).
    """
    if not db:
        return []
    enq = _parse_db_ts(db.get("queue_enqueued_max"))
    att = _parse_db_ts(db.get("queue_last_attempt_max"))
    if enq is None:
        return []
    if att is None:
        return ["document_queue 에 last_attempt_at 이 찍힌 행이 하나도 없다"
                " (DocWorker 가 이 큐를 한 번도 만지지 않았다) - 최신 적재 %s"
                % enq.strftime("%Y-%m-%d")]
    gap = enq - att
    if gap <= timedelta(days=QUEUE_STALL_DAYS):
        return []
    out = ["document_queue: 최신 적재 %s / DocWorker 마지막 처리 %s - %d일째 정체"
           " (크롤은 계속 쌓는데 아무도 빼지 않는다)"
           % (enq.strftime("%Y-%m-%d"), att.strftime("%Y-%m-%d"), gap.days)]
    total = db.get("queue_pending_total") or 0
    moot = db.get("queue_pending_moot") or 0
    if total and moot:
        out.append("pending %d건 중 %d건(%.0f%%)은 기일이 이미 지나 이제 수집해도"
                    " 의미가 없다 - 정체가 길어질수록 이 비율만 늘어난다"
                    % (total, moot, 100.0 * moot / total))
    return out


def run_report():
    print("=" * 70)
    print(" 예약 실행 건강 감사 (읽기 전용) - %s" % datetime.today().strftime("%Y-%m-%d %H:%M"))
    print("=" * 70)
    print("  저장소: %s" % ROOT)

    exp = expected_tasks()
    print()
    print("[1] 등록 상태")
    print("    등록 스크립트가 정의한 작업: %d개" % len(exp))
    tasks = query_tasks()
    if tasks is None:
        print("    * 스케줄러를 조회하지 못했다. '작업이 없다'와 다르다 - 판정 보류.")
        hits = {}
    else:
        print("    스케줄러 전체 작업: %d개" % len(tasks))
        dropped = PARSE_STATS["column_mismatch"]
        if dropped:
            print("    ★ 칸 수가 맞지 않아 **버린 행 %d개** - 그만큼 이 감사에서"
                  " 보이지 않는 작업이 있을 수 있다(0개가 아니라 미확인이다)." % dropped)
        hits = repo_pointing_tasks(tasks)
        print("    이 저장소를 가리키는 작업: %d개" % len(hits))
        known = set(n for n, _b, _t in exp)
        for name in sorted(hits):
            tag = "" if name in known else "   <- 등록 스크립트가 모르는 이름이다"
            print("      - %s%s" % (name, tag))
        missing = [n for n, _b, _t in exp if n not in tasks]
        if missing:
            print("    등록되지 않은 정의: %s" % ", ".join(missing))

    print()
    print("[2] 마지막 실행")
    if not hits:
        print("    돌아본 작업이 없다 (등록 0개).")
    for name in sorted(hits):
        rec = hits[name]
        print("      %-28s 마지막 %s / 결과 %s / 다음 %s"
              % (name,
                 _get(rec, "Last Run Time", "마지막 실행 시간") or "-",
                 _get(rec, "Last Result", "마지막 결과") or "-",
                 _get(rec, "Next Run Time", "다음 실행 시간") or "-"))

    print()
    print("[3] 이 저장소에 남은 흔적")
    logs = {}
    for rel in sorted(set(LOG_OF_BAT.values())):
        state = log_state(rel)
        logs[rel] = state
        if not state["exists"]:
            print("      %-22s (파일 없음)" % rel)
        else:
            print("      %-22s 마지막 갱신 %s"
                  % (rel, state["mtime"].strftime("%Y-%m-%d %H:%M")))
            if state["marker"]:
                print("      %-22s 마지막 마커 %s" % ("", state["marker"][:80]))
            else:
                print("      %-22s 마커 없음(구 형식). 마지막 줄: %s"
                      % ("", (state.get("last_line") or "(빈 파일)")[:70]))

    db = db_state()
    if db is None:
        print("      DB 없음 - 데이터 축 판정 보류")
    else:
        print()
        print("      auction_item 최신 수집일 : %s" % db["crawl_date_max"])
        print("      앞으로 남은 기일 물건     : %d건 (마지막 기일 %s)"
              % (db["future_items"], db["last_auction_date"]))
        print("      document_queue            : %s" % (db["queue"] or "{}"))
        print("      doc_raw                   : %s" % db["doc_raw"])
        print("      큐 최신 적재/최근 처리     : %s / %s"
              % (db.get("queue_enqueued_max") or "-", db.get("queue_last_attempt_max") or "-"))

    print()
    print("[4] 축 사이의 모순")
    bad = contradictions(hits, logs, db) + queue_stall_signal(db)
    if not bad:
        print("      모순 없음 (또는 판정할 재료가 없다)")
    for b in bad:
        print("      * " + b)

    print()
    print("[5] 검색 잔여 기간")
    if db is not None:
        if db["future_items"] == 0:
            print("      * 앞으로 기일이 남은 물건이 0건이다. 기본 검색은 이미 비어 있다.")
        else:
            print("      남은 물건 %d건, 마지막 기일 %s"
                  % (db["future_items"], db["last_auction_date"]))
            print("      그 다음 날부터 기본 검색 결과가 0건이 된다.")

    print()
    print("=" * 70)
    print(" 이 스크립트는 아무것도 바꾸지 않는다. 등록은 승인 영역이다.")
    return 0


# ---------------------------------------------------------------------------
# selftest - 모순 탐지기가 **실제로 우는지** 확인한다.
#
# 이 파일에 넣는 이유: 별도 테스트 파일에서 이 미추적 스크립트를 import 하면
# "추적 파일이 미추적 파일을 import 한다" 가드에 걸린다(BUGS #105 계열).
# ---------------------------------------------------------------------------
def selftest():
    fails = []

    def check(name, actual, expected):
        ok = actual == expected
        print("  [%s] %s: %r (기대 %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
        if not ok:
            fails.append(name)

    print("--- selftest: 모순 탐지기 ---")

    # ★ 칸 수가 어긋난 행을 **조용히 버리지 않는가** (2026-08-19 Sprint 217).
    #   버려진 행 하나가 곧 "감사에서 사라진 작업 하나"이고, 그 결과는
    #   "그런 작업 없음"이라는 정상과 똑같은 모양으로 나온다.
    good_csv = ('"HostName","TaskName","Status"' + chr(10)
                + '"PC","' + '\\' + 'A","Ready"' + chr(10))
    bad_csv = good_csv + '"PC","' + '\\' + 'B","Ready","EXTRA"' + chr(10)
    parsed_good = parse_schtasks_csv(good_csv)
    check("정상 CSV 는 그대로 읽는다", sorted(parsed_good or {}), ["\\A"])
    check("정상 CSV 에서는 버린 행이 없다", PARSE_STATS["column_mismatch"], 0)
    parsed_bad = parse_schtasks_csv(bad_csv)
    check("칸 수가 어긋난 행은 읽히지 않는다", sorted(parsed_bad or {}), ["\\A"])
    check("★ 버린 행이 기록된다(조용히 사라지지 않는다)",
          PARSE_STATS["column_mismatch"], 1)

    now = datetime.today()
    rec_ok = {"TaskName": "T", "Last Result": "0",
              "Last Run Time": now.strftime("%Y-%m-%d %H:%M:%S")}

    # (1) 성공했다는데 로그가 훨씬 오래됐다 -> 모순 1건
    old_logs = {"logs/daily_run.log": {"exists": True, "mtime": now - timedelta(days=7),
                                       "marker": None}}
    got = contradictions({"T": rec_ok}, old_logs, None)
    check("성공인데 흔적이 없으면 지목한다", len(got), 1)

    # (2) 로그가 실행 직후에 갱신됐다 -> 모순 없음 (대조군)
    fresh = {"logs/daily_run.log": {"exists": True, "mtime": now, "marker": None}}
    check("흔적이 있으면 지목하지 않는다", len(contradictions({"T": rec_ok}, fresh, None)), 0)

    # (3) 결과가 실패면 이 검사의 소관이 아니다 (대조군)
    rec_bad = dict(rec_ok, **{"Last Result": "1"})
    check("실패한 작업은 이 검사가 다루지 않는다",
          len(contradictions({"T": rec_bad}, old_logs, None)), 0)

    # (4) 실행 시각을 못 읽으면 추측하지 않는다 (대조군)
    rec_unk = dict(rec_ok, **{"Last Run Time": "알 수 없음"})
    check("실행 시각을 못 읽으면 판정하지 않는다",
          len(contradictions({"T": rec_unk}, old_logs, None)), 0)

    # (5) 등록 스크립트 파싱이 조용히 0건이 되지 않는다
    try:
        n = len(expected_tasks())
    except RuntimeError:
        n = -1
    check("등록 스크립트에서 작업 정의를 읽는다 (3개)", n, 3)

    # (6) ★ 헤더가 첫 칸이 아니어도 읽는가 - 실제로 여기서 249개를 0개로 읽었다.
    #     `/v` 출력의 1번 칸은 "호스트 이름"이고 작업 이름은 2번 칸이다.
    HEADER_KO = '"호스트 이름","작업 이름","다음 실행 시간","마지막 결과"'
    fixture = HEADER_KO + chr(10) + '"HOST","\\MyTask","2026-08-19 9:00:00","0"'
    parsed = parse_schtasks_csv(fixture)
    check("작업 이름이 2번 칸이어도 읽는다", sorted(parsed or {}), ["\\MyTask"])

    # (7) 영문 헤더도 읽는다 (로캘이 바뀌어도 조용히 0개가 되면 안 된다)
    fixture_en = ('"HostName","TaskName","Next Run Time","Last Result"' + chr(10)
                  + '"HOST","\\EnTask","2026-08-19 9:00:00","0"')
    check("영문 헤더도 읽는다", sorted(parse_schtasks_csv(fixture_en) or {}), ["\\EnTask"])

    # (8) 읽을 것이 있었는데 못 뽑았으면 0개가 아니라 **조회 실패**다
    check("헤더를 못 찾으면 None(조회 실패)이다",
          parse_schtasks_csv('"쓰레기","줄"' + chr(10) + '"a","b"'), None)
    check("출력이 비면 None 이다", parse_schtasks_csv(""), None)

    # (9) 큐 정체 판정 (2026-08-25 신설) - 실제로 6주 뒤처진 상태를 이 세션에서
    #     발견하고서야 이 감사기에 판정 자체가 없다는 것을 알았다.
    now_iso = datetime.today().isoformat()
    stale_iso = (datetime.today() - timedelta(days=45)).isoformat()
    check("ISO 타임스탬프를 읽는다(schtasks 형식이 아니다)",
          _parse_db_ts(now_iso) is not None, True)
    check("빈 값은 None(추측하지 않는다)", _parse_db_ts(""), None)
    check("깨진 문자열도 None", _parse_db_ts("어제쯤"), None)

    check("정체 없음(문턱 안쪽)이면 지목하지 않는다",
          len(queue_stall_signal({"queue_enqueued_max": now_iso,
                                  "queue_last_attempt_max": now_iso})), 0)
    stalled = queue_stall_signal({"queue_enqueued_max": now_iso,
                                  "queue_last_attempt_max": stale_iso,
                                  "queue_pending_total": 100,
                                  "queue_pending_moot": 40})
    check("45일 뒤처지면 지목한다", len(stalled) >= 1, True)
    check("moot 비율도 함께 보고한다", any("40" in s and "%" in s for s in stalled), True)
    check("last_attempt_at 이 아예 없으면(한 번도 안 만짐) 그것도 지목한다",
          len(queue_stall_signal({"queue_enqueued_max": now_iso,
                                  "queue_last_attempt_max": None})), 1)
    check("둘 다 없으면 판정하지 않는다(재료 없음)",
          len(queue_stall_signal({})), 0)

    print()
    if fails:
        print("selftest 실패 %d건: %s" % (len(fails), fails))
        return 1
    print("selftest 전체 통과")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(run_report())
