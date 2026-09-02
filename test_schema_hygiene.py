"""
DB 스키마/커넥션 위생 회귀 테스트 (jose 불필요 — storage.database만 import).

test_api_regression.py를 정적 감사하며 발견한, 실행 전에는 드러나지 않았을 두 결함의 회귀
방어다(2026-08-08 Sprint 31):

    1) get_connection(enforce_foreign_keys=False) 시그니처 — 23번 섹션이 이 키워드 인자를
       호출하는데 예전 storage/database.py:get_connection()은 인자를 받지 않았다.
    2) favorites/search_presets의 deleted_at/deleted_by 컬럼 — 28번 섹션(Soft Delete,
       CTO 승인 10건 #6)이 검증하는데 Migration 010~016 복구 당시에는 코드 참조가 없다는
       이유로 의도적으로 빠뜨렸었다(실제로는 migration **016**에 함께 들어 있다 —
       2026-08-11 Sprint 51 확인. 과거 기록의 "017"은 잘못된 번호였고, 017은 Sprint 51에서
       document_collect_failures 부트스트랩 누락 복구용으로 새로 만들어졌다).

    python test_schema_hygiene.py
"""
import sys
import codecs
import ast
import os
import re
import sqlite3
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage.database as dbmod

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


def test_get_connection_fk_parameter():
    print("\n--- 1. get_connection(enforce_foreign_keys=...) ---")
    c1 = dbmod.get_connection()
    check("default (no arg) has FK ON", c1.execute("PRAGMA foreign_keys").fetchone()[0], 1)
    c1.close()

    c2 = dbmod.get_connection(enforce_foreign_keys=True)
    check("explicit True has FK ON", c2.execute("PRAGMA foreign_keys").fetchone()[0], 1)
    c2.close()

    c3 = dbmod.get_connection(enforce_foreign_keys=False)
    check("explicit False has FK OFF", c3.execute("PRAGMA foreign_keys").fetchone()[0], 0)
    c3.close()


def test_soft_delete_columns():
    print("\n--- 2. soft delete columns (favorites/search_presets) ---")
    conn = dbmod.get_connection()
    try:
        for table in ("favorites", "search_presets"):
            cols = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)]
            check("%s has deleted_at" % table, "deleted_at" in cols, True)
            check("%s has deleted_by" % table, "deleted_by" in cols, True)
    finally:
        conn.close()


# `migration_history` 에는 있는데 디스크에 파일이 없는 항목 중 **설명이 끝난 것**.
# 016/017 은 번호가 재사용된 자리다 - 옛 파일이 적용된 뒤 같은 번호로 다른 내용이
# 들어왔고(016_create_audit_and_credit_logs / 017_create_document_collect_failures 가
# 지금 그 번호를 쓴다), 옛 이름만 이력에 남았다. 그 시절 열(deleted_at/deleted_by)은
# 지금도 살아 있어(위 2번 검사가 확인한다) 잃어버린 것이 없다.
KNOWN_APPLIED_WITHOUT_FILE = {
    "016_create_audit_logs.sql",
    "017_add_soft_delete_columns.sql",
}


def test_migration_history_complete():
    """디스크 .sql 과 `migration_history` 를 **양방향으로** 본다.

    한쪽만 보던 검사였다 (2026-09-01 확장). `on_disk - applied` 만 확인했으므로
    **반대 방향 - 적용됐다고 기록됐는데 파일이 없는 것 - 은 영원히 보이지 않았다.**
    실제로 그 사각지대에 3건이 들어와 있었다:

        027_drop_redundant_favorite_notes_index.sql
        028_auction_filed_date.sql
        029_drop_measured_prefix_indexes.sql

    셋 다 2026-08-30~31 에 적용 기록이 남았는데 **디스크에도 git 이력 어디에도 없다**
    (`git log --all -- storage/migrations/027*` 등 전부 0건). 즉 마이그레이션이
    DB 에 적용된 뒤 파일이 커밋되지 않고 사라졌다.

    왜 이 방향이 중요한가 - **저장소가 자기 DB 스키마를 더 이상 재현하지 못한다.**
    새로 clone 해서 부트스트랩하면 라이브와 다른 스키마가 나온다(실측: 라이브에만
    `auction.filed_date`, fresh 에만 인덱스 4개). `test_bootstrap.py` 의 3-B 가 그
    **결과**는 잡지만, 원인이 "파일이 없어졌다"라는 것은 말해 주지 못해 KNOWN_* 목록에
    등재하는 것으로 조용히 덮일 수 있다. 여기서 원인을 직접 지목한다.
    """
    print("\n--- 3. migration_history completeness (디스크 .sql 전수) ---")
    conn = dbmod.get_connection()
    try:
        applied = {r[0] for r in conn.execute("SELECT filename FROM migration_history")}
        expected_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "migrations")
        on_disk = {f for f in os.listdir(expected_dir) if f.endswith(".sql")}
        missing = sorted(on_disk - applied)
        check("every .sql file on disk is recorded as applied", missing, [])

        # 검사가 공허하지 않은지 먼저 본다 - 양쪽이 비면 위/아래가 자동으로 통과한다.
        check_true("비교 대상이 실재한다(디스크 %d개 / 적용 %d건)"
                   % (len(on_disk), len(applied)),
                   len(on_disk) > 0 and len(applied) > 0, (len(on_disk), len(applied)))

        orphan = sorted(applied - on_disk - KNOWN_APPLIED_WITHOUT_FILE)
        check("★ 적용됐다고 기록됐는데 파일이 없는 마이그레이션 없음", orphan, [])

        resolved = sorted(KNOWN_APPLIED_WITHOUT_FILE - (applied - on_disk))
        if resolved:
            print("   [정리됨] 파일이 돌아왔다 - KNOWN_APPLIED_WITHOUT_FILE 에서 "
                  "빼십시오: %s" % ", ".join(resolved))
    finally:
        conn.close()


def test_requirements_covers_all_imports():
    """requirements.txt가 소스의 실제 third-party import를 전부 덮는가.

    2026-08-11 Sprint 54 신설. 이 저장소에는 8일 동안 의존성 목록이 아예 없었고, 그 사이
    크롤 환경(Anaconda)이 사라지면서 **무엇을 다시 깔아야 하는지조차 알 수 없는 상태**가
    됐다. requirements.txt를 만든 것으로 끝내면 다음 import가 추가되는 순간 똑같이 어긋난다.
    그래서 목록을 사람이 관리하는 대신 **소스에서 매번 다시 도출해 비교**한다.
    """
    import ast

    print("\n--- 4. requirements.txt <-> 소스 import 일치 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    skip_dirs = {".next", "node_modules", ".git", "__pycache__", ".venv", "venv", "logs", "data"}

    # 저장소 내부 모듈(로컬 패키지/스크립트)은 third-party가 아니다.
    local = set()
    for entry in os.listdir(root):
        path = os.path.join(root, entry)
        if os.path.isdir(path) and entry not in skip_dirs:
            local.add(entry)
        elif entry.endswith(".py"):
            local.add(entry[:-3])

    # ★ **저장소에 실제로 들어가는 .py만** 센다 (2026-08-13 Sprint 99).
    #
    #   예전에는 파일시스템을 그냥 훑었다. 그래서 `.gitignore` 대상인 로컬 실험 스크립트까지
    #   "소스"로 셌고, 이 검사는 **다른 환경에는 존재하지도 않는 집합**을 기준으로 통과하고
    #   있었다. 즉 이 검사 자체가 false success였다.
    #
    #   실측(Sprint 99): `.gitignore`의 `step*.py`에 걸리는 파일이 **65개** 있고, 그중
    #   `step8_verify.py`만 `requests`를 import한다. 그 65개를 빼고 돌리면(=fresh clone)
    #
    #       [FAIL] 목록에만 있고 소스에서 안 쓰는 항목 없음: ['requests']
    #
    #   즉 **새로 clone한 환경에서는 이 검사가 깨진다.** 로컬에서만 통과하고 CI에서 깨지는,
    #   가장 알아채기 어려운 종류다.
    #
    #   기준을 `git`에 맡긴다 — `--cached`(추적 중) + `--others --exclude-standard`
    #   (아직 추적 안 되지만 무시 대상도 아닌 새 파일). 무시 대상만 정확히 빠진다.
    #   양방향 모두에 필요하다: 무시된 스크립트가 목록에 없는 걸 import하면 반대로
    #   있지도 않은 누락이 보고된다.
    py_files = []
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        if out.returncode == 0:
            for rel in out.stdout.splitlines():
                if not rel.endswith(".py"):
                    continue
                if rel.split("/", 1)[0] in skip_dirs:
                    continue
                path = os.path.join(root, rel.replace("/", os.sep))
                if os.path.isfile(path):
                    py_files.append(path)
    except Exception:
        py_files = []

    if not py_files:
        # git이 없거나 저장소가 아니면 예전 방식으로 되돌린다 — 검사를 아예 잃는 것보다는 낫다.
        print("    [주의] git 파일 목록을 쓸 수 없어 파일시스템 전수로 대체한다"
              " (무시된 로컬 스크립트가 섞일 수 있음)")
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            py_files += [os.path.join(dirpath, f) for f in filenames if f.endswith(".py")]

    # import 최상위 이름 -> pip 배포판 이름. 둘이 다른 경우만 적는다.
    DIST_NAME = {
        "dotenv": "python-dotenv",
        "jose": "python-jose",
        "webdriver_manager": "webdriver-manager",
        "yaml": "pyyaml",
        "bs4": "beautifulsoup4",
        "PIL": "pillow",
    }

    imported = {}
    parse_failures = []
    for path in py_files:
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                tree = ast.parse(fh.read())
        except SyntaxError as exc:
            parse_failures.append("%s: %s" % (os.path.relpath(path, root), exc.msg))
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # 상대 import는 항상 로컬
                    continue
                if node.module:
                    names = [node.module]
            for name in names:
                top = name.split(".")[0]
                if top in local or top in sys.stdlib_module_names:
                    continue
                imported.setdefault(top, set()).add(os.path.relpath(path, root))

    # .py가 파싱조차 안 되면 그 파일의 import는 조용히 빠진다 -> 검사에 구멍이 생긴다.
    check("모든 .py가 파싱된다(구멍 없는 전수 검사)", parse_failures, [])

    req_path = os.path.join(root, "requirements.txt")
    check("requirements.txt가 존재한다", os.path.exists(req_path), True)
    if not os.path.exists(req_path):
        return

    listed = set()
    with open(req_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            # "python-jose[cryptography]==3.5.0" -> "python-jose"
            for sep in ("==", ">=", "<=", "~=", ">", "<", "!=", "["):
                if sep in line:
                    line = line.split(sep, 1)[0]
            listed.add(line.strip().lower().replace("_", "-"))

    missing = sorted(
        "%s (%s)" % (mod, sorted(files)[0])
        for mod, files in imported.items()
        if DIST_NAME.get(mod, mod).lower().replace("_", "-") not in listed
    )
    check("소스가 import하는 third-party가 전부 목록에 있다", missing, [])

    # 반대 방향: 목록에만 있고 아무도 안 쓰는 항목은 "설치했는데 왜 필요한지 모르는" 상태를 만든다.
    used_dists = {DIST_NAME.get(m, m).lower().replace("_", "-") for m in imported}

    # ── httpx: 예외가 아니라 **강제되는 요구사항**으로 다룬다 (2026-08-14) ──────
    #
    # 예전에는 여기서 `- {"httpx"}`로 조용히 빼기만 했다("import 스캔에 안 잡힐 수 있다").
    # 그러면 검사가 **한 방향만** 본다 — 누가 requirements 에서 httpx 를 지워도
    # `stale`이 비어 통과한다. 실제로 지우기 쉬운 항목이다: 소스 전체에서
    # `import httpx`가 **0건**이라 "안 쓰는 의존성"처럼 보인다(2026-08-14 전수 확인).
    #
    # 그런데 지우면 TestClient 기반 회귀가 통째로 못 돈다. 실측 근거:
    #
    #   from fastapi.testclient import TestClient  -> sys.modules 에 httpx 적재  True
    #   import api_server (운영 경로)               -> httpx 적재                False
    #
    # 즉 **테스트 전용이지만 없어서는 안 되는** 의존성이다. 그래서 빼는 대신
    # "반드시 있어야 한다"를 직접 단언하고, 그 근거(TestClient 사용 테스트가 실재함)도
    # 함께 확인한다. 근거가 사라지면(TestClient 를 아무도 안 쓰게 되면) 그때 다시 판단한다.
    #
    # ★ starlette 이 `httpx` 대신 `httpx2` 를 권고하는 경고를 낸다(deprecated).
    #   전환은 starlette 업그레이드와 함께 해야 하므로 지금 버전만 바꾸지 않는다 —
    #   자세한 근거는 `requirements.txt` 의 httpx 주석 참고.
    tc_users = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8-sig") as fh:
                    if "TestClient" in fh.read():
                        tc_users.append(os.path.relpath(fp, root))
            except OSError:
                continue

    check_true("httpx 가 requirements 에 있다(TestClient 회귀의 전제)",
               "httpx" in listed,
               "소스가 직접 import 하지 않아 '안 쓰는 의존성'처럼 보이지만, 지우면 "
               "TestClient 기반 테스트가 전부 실행되지 않는다")
    check_true("httpx 가 필요한 근거가 실재한다(TestClient 사용 파일 존재)",
               len(tc_users) > 0, tc_users)
    print("   TestClient 사용 파일 %d개 -> httpx 필수" % len(tc_users))

    stale = sorted(listed - used_dists - {"httpx"})
    check("목록에만 있고 소스에서 안 쓰는 항목 없음", stale, [])

    print("   소스에서 발견한 third-party %d개: %s" % (len(imported), ", ".join(sorted(imported))))


# ---------------------------------------------------------------------------
# 5. ErrorCode: 정의 <-> 문서 <-> 실제 방출 3자 대조 (2026-08-13 Sprint 72 신설)
#
# `docs/ERROR_CODES.md`는 "이 문서가 아니라 코드가 기준"이라고 못박고 40개를 나열한다.
# 그런데 **정의됐다는 것과 실제로 응답에 실린다는 것은 다르다.** 실측하니 40개 중 19개만
# 방출되고 21개는 어디서도 쓰이지 않았다.
#
# 이유는 이 저장소에 실패 응답이 두 가지 형태로 있기 때문이고, 그것 자체는 의도된 상태다:
#
#   error_response(code, msg)  -> HTTP 200 + {success:false, error:"CODE", message:...}
#                                 payments / search_presets / registry / favorites 4개 파일
#   raise HTTPException(...)   -> HTTP 4xx/5xx + {"detail": "..."}  (코드 없음)
#                                 auth / admin / subscriptions / item / search
#
# `api/auth.py:fail()`의 주석이 그 판단을 이미 적어 뒀다 — "코드가 붙지 않은 기존 호출부를
# 억지로 특정 코드로 몰아넣으면 오히려 오해를 부른다". 그래서 이 검사는 **미방출 코드를
# 결함으로 보지 않는다.** 대신 지금의 경계를 그대로 고정해서 다음 두 가지를 잡는다:
#
#   (1) 새 코드를 enum에 넣고 문서에 안 적는 것 / 문서에만 있고 정의가 없는 것
#   (2) 방출되던 코드가 조용히 사라지거나, 문서 없이 새로 방출되기 시작하는 것
#
# 프런트(`src/lib/api.ts:ERROR_CODES`)가 분기에 쓰는 값이라 (2)는 화면 동작에 직결된다.
# ---------------------------------------------------------------------------

# 현재 실제로 응답에 실리는 코드. 늘리거나 줄일 때는 docs/ERROR_CODES.md도 함께 고친다.
EMITTED_ERROR_CODES = {
    # api/v1/payments.py
    "PAY_INVALID_TYPE", "PAY_INVALID_PLAN", "PAY_INVALID_BILLING_CYCLE",
    "PAY_AMOUNT_MISMATCH", "PAY_NO_TARGET_REQUEST", "PAY_ALREADY_PROCESSED",
    "PAY_FAILED", "PAY_NOT_FOUND", "PAY_INVALID_TRANSITION",
    # api/v1/search_presets.py
    "SEARCH_PRESET_NAME_REQUIRED", "SEARCH_PRESET_NAME_TOO_LONG",
    "SEARCH_PRESET_TOO_LARGE", "SEARCH_PRESET_LIMIT_EXCEEDED", "SEARCH_PRESET_NOT_FOUND",
    # api/v1/registry.py
    "REGISTRY_SUBSCRIPTION_REQUIRED", "REGISTRY_NOT_COMPLETED", "REGISTRY_DOCUMENT_NOT_FOUND",
    # api/v1/favorites.py
    "FAVORITE_ALREADY_EXISTS", "FAVORITE_NOT_FOUND",
    # api/v1/favorite_import.py (2026-08-28 마이리스트 가져오기)
    "FAVORITE_IMPORT_EMPTY", "FAVORITE_IMPORT_TOO_LARGE",
    "FAVORITE_NOTE_UNAVAILABLE", "ITEM_NOT_FOUND",
}


def _error_code_names(root):
    """api/constants.py:ErrorCode에 정의된 이름들."""
    import ast

    path = os.path.join(root, "api", "constants.py")
    with open(path, encoding="utf-8-sig") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ErrorCode":
            return [st.targets[0].id for st in node.body
                    if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name)]
    return []



# ---------------------------------------------------------------------------
# 프런트 상태 라벨표가 백엔드 enum 을 덮는가 (2026-09-01 신설)
#
# 화면은 백엔드 상태값에 한국어 라벨을 붙여 보여 준다. 라벨표에 없는 값이 오면
# **원본 영문 코드가 그대로 사용자에게 보인다** (`LABEL[v] ?? v`). 이 폴백 자체는
# 의도된 것이다 — `mypage/page.tsx` 가 *"임의로 뭉뚱그리면 운영 중 새로 생긴 상태를
# 사용자가 오해한다"* 고 적어 뒀고, 그 판단이 맞다.
#
# 문제는 **enum 에 이미 선언돼 있는데 라벨이 없는 값**이다. 그건 "새로 생긴 상태"가
# 아니라 처음부터 빠뜨린 것이고, 지금 안 보이는 이유는 그 상태에 도달하는 경로가
# 아직 없기 때문일 뿐이다(결제는 MockProvider 라 항상 성공한다).
#
# 그래서 **덮지 못한 값을 결함으로 세지 않고 목록으로 못박는다.** 지금의 경계를
# 고정하는 것이 목적이다 — 새 상태가 생기면 이 검사가 붉어지고, 그때 라벨을 쓸지
# (사용자 문구는 제품 결정) 판단하면 된다. `special_conditions` 를 다룬 방식과 같다.
# ---------------------------------------------------------------------------

# 라벨이 없는 채로 남아 있는 값과 그 이유. **줄어드는 것도 늘어나는 것도 붉어진다.**
KNOWN_UNLABELED = {
    # 결제창 호출 전/중 상태. MockProvider 는 항상 즉시 성공이라 지금은 도달하지
    # 않는다. 실 PG(KG이니시스) 연동 시 사용자가 결제창을 닫으면 실제로 남는다.
    # 그때 어떤 문구를 보여 줄지는 제품 결정이라 여기서 정하지 않는다.
    ("PAYMENT_LABEL", "PaymentStatus"): {"CREATED", "READY", "REQUESTED"},
    # 상세 화면은 PAYMENT_REQUIRED 를 라벨이 아니라 **결제 버튼 분기**로 그린다
    # (그 파일의 주석이 그렇게 적어 뒀고, JSX 에 실제 분기가 있다).
    ("REGISTRY_STATUS_LABEL", "RegistryRequestStatus"): {"PAYMENT_REQUIRED"},
}

# (프런트 상수 이름, 파일, 백엔드 enum 이름)
LABEL_TABLES = [
    ("SUBSCRIPTION_LABEL", "src/app/mypage/page.tsx", "SubscriptionStatus"),
    ("PAYMENT_LABEL", "src/app/mypage/page.tsx", "PaymentStatus"),
    ("PAYMENT_TYPE_LABEL", "src/app/mypage/page.tsx", "PaymentType"),
    ("REGISTRY_LABEL", "src/app/mypage/page.tsx", "RegistryRequestStatus"),
    ("REGISTRY_STATUS_LABEL", "src/app/properties/[id]/page.tsx", "RegistryRequestStatus"),
    ("DOC_TYPE_LABEL", "src/app/properties/[id]/page.tsx", "DocumentType"),
    # ★ `DOC_STATUS_LABEL`(문서수집상태 배지)은 여기 없다 - 중복이 아니라 **자리**의
    #   문제다. `test_queue_safety_invariants.py` 의 문서 상태 어휘 계약 (e) 가
    #   이미 `DOCUMENT_STATUSES_IN_USE` 와 대조하고 있고, 그 파일이 그 어휘의
    #   정본을 지키는 자리다. 같은 규칙을 두 곳에서 세면 한쪽만 고쳐지는 날이 온다.
]


def _enum_values(root, name):
    """api/constants.py 의 StrEnum 값들. 이름이 아니라 **값**을 본다."""
    import ast

    path = os.path.join(root, "api", "constants.py")
    with open(path, encoding="utf-8-sig") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            out = set()
            for st in node.body:
                if (isinstance(st, ast.Assign) and isinstance(st.value, ast.Constant)
                        and isinstance(st.value.value, str)):
                    out.add(st.value.value)
            return out
    return set()


def _label_keys(root, rel, const):
    """`const NAME: Record<string, string> = { A: '..', B: '..' }` 의 키들."""
    import re

    path = os.path.join(root, rel.replace("/", os.sep))
    with open(path, encoding="utf-8-sig") as fh:
        src = fh.read()
    m = re.search(r"const\s+%s\s*:\s*Record<[^>]*>\s*=\s*\{(.*?)\n\}" % re.escape(const),
                  src, re.S)
    if not m:
        return None
    return set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)\s*:", m.group(1), re.M))




# ---------------------------------------------------------------------------
# 프런트 법원 목록이 백엔드 마스터와 같은가 (2026-09-01 신설)
#
# `src/app/search/SearchForm.tsx` 의 `COURT_LIST` 는 **`config/courts.py:ALL_COURTS`
# 를 손으로 옮겨 적은 사본**이다. 그 파일의 주석이 스스로 그렇게 적어 뒀다 —
#
#     "config/courts.py(ALL_COURTS)의 실제 법원 마스터 데이터를 그대로 옮겼다 —
#      같은 목록을 두 곳에서 관리하므로, config/courts.py가 바뀌면 이 목록도 함께 갱신해야 한다"
#
# 그런데 **"함께 갱신해야 한다"를 지키는 것이 그 주석뿐이었다**(2026-09-01 전수 확인:
# 두 목록을 대조하는 검사 0건). 어긋나면 어떻게 보이는가 —
#
#   백엔드에만 있는 법원   화면 드롭다운에 아예 안 나온다. 그 법원 물건은 **영원히
#                         법원으로 검색할 수 없다.** 오류도 빈 결과도 아니고 선택지가 없다
#   프런트에만 있는 법원   고를 수는 있는데 `court_name` LIKE 매칭이 0건이다.
#                         "그 법원은 물건이 없네"로 보인다
#
# `docs/BUGS.md` #33(물건종류 69개 중 60개가 항상 0건)이 정확히 이 모양이었고,
# 발견까지 오래 걸린 이유도 같다. 그래서 어휘 표를 DB 와 대조하는 검사를 만든 것처럼
# (`test_property_type_vocabulary.py`) 이 사본도 정본과 대조한다.
#
# ★ 사본을 없애지 않는 이유: 프런트가 런타임에 법원 목록 API 를 부르게 바꾸는 것은
#   화면 로딩 순서와 API 계약을 바꾸는 일이라 최소 변경이 아니다. 지금 필요한 것은
#   "사본이 정본과 갈라지지 않는다"는 보장이고, 그것은 검사로 충분하다.
# ---------------------------------------------------------------------------
# ★ `test_court_list_integrity()`(위 §9) 와 겹치지 않는다 — 거기는 마스터 자체의
#   **내부** 무결성(개수 60 / 중복 / 빈 값 / code==name / region ⊆ SIDO_LIST)을 보고,
#   여기는 **사본과의 대조**를 본다. 둘 다 필요하다 — 마스터가 완벽해도 사본이
#   낡으면 화면은 틀리고, 사본이 같아도 마스터가 깨지면 크롤이 틀린다.

def test_frontend_court_list_matches_backend_master():
    print("\n--- 프런트 법원 목록 <-> config/courts.py 마스터 ---")
    import re

    root = os.path.dirname(os.path.abspath(__file__))
    try:
        from config.courts import ALL_COURTS
    except ImportError as exc:
        check_true("config.courts 를 불러왔다", False, str(exc))
        return

    back_pairs = {(c.name, c.region) for c in ALL_COURTS}
    check_true("검사가 공허하지 않다(백엔드 마스터를 읽었다) - %d개" % len(back_pairs),
               len(back_pairs) >= 40, len(back_pairs))

    form = os.path.join(root, "src", "app", "search", "SearchForm.tsx")
    check_true("SearchForm.tsx 가 있다", os.path.exists(form), form)
    if not os.path.exists(form):
        return
    with open(form, encoding="utf-8-sig") as fh:
        src = fh.read()

    m = re.search(r"const COURT_LIST: CourtInfo\[\] = \[(.*?)\n\]", src, re.S)
    check_true("COURT_LIST 를 찾았다", m is not None,
               "-> 상수 이름이나 타입이 바뀌었다면 이 검사도 함께 고쳐야 한다")
    if not m:
        return
    front_pairs = set(re.findall(r"name:\s*'([^']+)'\s*,\s*region:\s*'([^']+)'", m.group(1)))
    check_true("검사가 공허하지 않다(프런트 목록을 읽었다) - %d개" % len(front_pairs),
               len(front_pairs) >= 40, len(front_pairs))

    # 이름+지역을 쌍으로 본다. 이름만 맞고 지역이 틀리면 드롭다운의 **다른 지역 밑에**
    # 들어가 사용자가 찾지 못한다(있는데 없는 것과 같다).
    check("★ 화면에서 고를 수 없는 법원(백엔드에만 있다)",
          sorted("%s(%s)" % p for p in (back_pairs - front_pairs)), [])
    check("★ 고를 수는 있는데 백엔드에 없는 법원(검색이 항상 0건)",
          sorted("%s(%s)" % p for p in (front_pairs - back_pairs)), [])

    # 자기 검증: 대조가 실제로 동작하는가.
    check_true("자기 검증: 가짜 항목은 차집합에 잡힌다",
               ("QA가짜지원", "QA") in ((front_pairs | {("QA가짜지원", "QA")}) - back_pairs))
    check_true("자기 검증: 실제 항목은 안 잡힌다",
               len(back_pairs & front_pairs) >= 40, len(back_pairs & front_pairs))

def test_frontend_labels_cover_backend_enums():
    print("\n--- 프런트 상태 라벨표 <-> 백엔드 enum ---")
    root = os.path.dirname(os.path.abspath(__file__))

    check_true("검사가 공허하지 않다(라벨표 목록이 있다)", len(LABEL_TABLES) >= 4, LABEL_TABLES)
    for const, rel, enum_name in LABEL_TABLES:
        values = _enum_values(root, enum_name)
        check_true("%s 를 읽었다(값 %d개)" % (enum_name, len(values)), len(values) >= 2, sorted(values))
        keys = _label_keys(root, rel, const)
        check_true("%s 를 %s 에서 찾았다" % (const, rel), keys is not None, rel)
        if keys is None or not values:
            continue

        # (1) 라벨표에 백엔드에 없는 값이 있으면 죽은 항목이다(오타이거나 사라진 상태).
        check("%s: 백엔드에 없는 값을 라벨링하지 않는다" % const, sorted(keys - values), [])

        # (2) 덮지 못한 값은 **고정된 목록과 정확히 같아야** 한다.
        expected = sorted(KNOWN_UNLABELED.get((const, enum_name), set()))
        check("★ %s: 라벨이 없는 값" % const, sorted(values - keys), expected)

    print("      -> 라벨이 없으면 사용자에게 영문 코드가 그대로 보인다(`LABEL[v] ?? v`)."
          " 폴백은 의도된 것이고, 여기서 고정하는 것은 **그 경계**다")

    # 자기 검증: 두 헬퍼가 실제로 값을 읽는가(빈 집합끼리 비교하면 무엇이든 통과한다).
    check_true("자기 검증: enum 값을 실제로 읽는다",
               "COMPLETED" in _enum_values(root, "RegistryRequestStatus"))
    check_true("자기 검증: 없는 enum 은 빈 집합이다",
               _enum_values(root, "QaNoSuchEnum") == set())
    check_true("자기 검증: 라벨 키를 실제로 읽는다",
               "ACTIVE" in (_label_keys(root, "src/app/mypage/page.tsx", "SUBSCRIPTION_LABEL") or set()))
    check_true("자기 검증: 없는 상수는 None 이다",
               _label_keys(root, "src/app/mypage/page.tsx", "QA_NO_SUCH_LABEL") is None)

def test_error_codes_defined_documented_emitted():
    print("\n--- 5. ErrorCode 정의/문서/방출 대조 ---")
    import re

    root = os.path.dirname(os.path.abspath(__file__))

    defined = _error_code_names(root)
    check("ErrorCode가 정의돼 있다", len(defined) > 0, True)
    check("정의에 중복이 없다", len(defined), len(set(defined)))
    defined_set = set(defined)

    # (1) 문서 대조 — 문서는 표 형식이라 `CODE` 백틱 안에 들어 있다.
    doc_path = os.path.join(root, "docs", "ERROR_CODES.md")
    check("ERROR_CODES.md가 존재한다", os.path.exists(doc_path), True)
    with open(doc_path, encoding="utf-8-sig") as fh:
        doc = fh.read()

    # 코드는 표의 **첫 칸**에만 온다. 둘째 칸(의미)에는 `SUPABASE_JWT_SECRET`,
    # `ADMIN_API_KEY` 같은 환경변수 이름이 들어 있어, 백틱만 보고 긁으면 그것들이
    # "정의되지 않은 유령 코드"로 잡힌다(실제로 잡혔다). 행 구조로 판별한다.
    #
    # 첫 칸이라도 "형식" 절의 접두사 표(`AUTH` / `PAY` / ...)는 코드가 아니다.
    # 문서가 스스로 정한 형식이 `<DOMAIN>_<SNAKE_CASE>`이므로 밑줄 유무로 정확히 갈린다.
    doc_codes = {c for c in re.findall(r"^\|\s*`([A-Z][A-Z0-9_]{3,})`\s*\|", doc, re.M)
                 if "_" in c}

    check("정의된 코드가 전부 문서에 있다", sorted(defined_set - doc_codes), [])
    check("문서의 코드가 전부 정의돼 있다", sorted(doc_codes - defined_set), [])

    # (2) 방출 대조 — api/ 안에서 ErrorCode.X 로 참조되는 것이 실제 방출이다.
    emitted = set()
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, "api")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.endswith(".py") or fn == "constants.py":
                continue
            with open(os.path.join(dirpath, fn), encoding="utf-8-sig") as fh:
                emitted |= set(re.findall(r"ErrorCode\.([A-Z0-9_]+)", fh.read()))

    check("방출되는 코드가 전부 정의돼 있다", sorted(emitted - defined_set), [])
    check("방출 집합이 고정된 목록과 같다(신규 방출)", sorted(emitted - EMITTED_ERROR_CODES), [])
    check("방출 집합이 고정된 목록과 같다(사라진 방출)", sorted(EMITTED_ERROR_CODES - emitted), [])

    # 프런트가 분기에 쓰는 코드는 반드시 실제로 방출돼야 한다 — 아니면 죽은 분기다.
    #
    # ★ 2026-09-01: 예전에는 **키만** 봤다. 그런데 런타임이 비교하는 것은 **값**이다.
    #
    #     result.error === ERROR_CODES.FAVORITE_NOT_FOUND
    #
    #   키가 맞아도 값에 오타가 있으면(`FAVORITE_NOT_FOUND: 'FAVORITE_NOTFOUND'`)
    #   이 분기는 **영원히 거짓**이 되고, "이미 삭제된 관심물건"이 실패로 보인다.
    #   오류도 로그도 없이 문구만 틀리는, 이 저장소가 반복해 겪은 모양이다.
    #   그래서 키/값을 함께 뽑아 **셋을 모두** 확인한다.
    api_ts = os.path.join(root, "src", "lib", "api.ts")
    check("프런트 api.ts 가 있다", os.path.exists(api_ts), True)
    if os.path.exists(api_ts):
        with open(api_ts, encoding="utf-8-sig") as fh:
            ts = fh.read()
        block = re.search(r"ERROR_CODES\s*=\s*\{(.*?)\}", ts, re.S)
        check("ERROR_CODES 블록을 찾았다", block is not None, True)
        pairs = re.findall(r"([A-Z][A-Z0-9_]{3,})\s*:\s*'([A-Z0-9_]+)'",
                           block.group(1)) if block else []
        # 이 검사가 공허해지는 유일한 길은 "하나도 못 찾는 것"이다. 먼저 막는다.
        check("검사가 공허하지 않다(프런트 분기 코드를 실제로 찾았다)", len(pairs) >= 3, True)

        front_keys = {k for k, _ in pairs}
        front_values = {v for _, v in pairs}
        check("★ 프런트 상수의 키와 값이 같다(오타 방지)",
              sorted(k for k, v in pairs if k != v), [])
        check("프런트가 분기하는 코드가 실제로 방출된다", sorted(front_keys - emitted), [])
        check("★ 프런트가 비교하는 **값**이 실제로 방출된다",
              sorted(front_values - emitted), [])
        check("프런트가 비교하는 값이 서버 enum 에 정의돼 있다",
              sorted(front_values - defined_set), [])
        print("   프런트 분기 코드 %d개 (키/값 일치)" % len(pairs))

    print("   정의 %d / 문서 %d / 실제 방출 %d (미방출 %d ― 의도된 상태, 위 주석 참고)"
          % (len(defined_set), len(defined_set & doc_codes), len(emitted),
             len(defined_set - emitted)))


# ---------------------------------------------------------------------------
# 6. storage/의 실동작 소스가 실제로 git에 추적되는가 (2026-08-13 Sprint 75 신설)
#
# 예전에는 `.gitignore`에 `storage/` 한 줄이 있었다. 의도는 크롤 데이터 산출물 제외였지만,
# 같은 디렉터리에 있는 **실동작 소스까지 통째로 빠졌다**:
#
#     storage/database.py          모든 API 라우트가 쓰는 DB 커넥션/큐 로직
#     storage/migrate_v4_1.py      v4.1 스키마 생성
#     storage/migrations/*.sql     001~018 마이그레이션 전부
#
# 이 사고의 성질이 나쁘다 - **파일은 디스크에 그대로 있으므로 아무도 눈치채지 못한다.**
# 로컬에서는 전부 정상 동작하고, 새로 clone한 환경에서만 스키마가 통째로 사라진다.
# 실제로 `docs/search-engine.md`와 `docs/crawler.md`는 그 상태를 보고
# "storage/database.py가 저장소에 없다"고 서술했고, 그 서술이 오래 남아 있었다.
#
# 2026-08-11 Sprint 51에 규칙이 정밀화됐다(`storage/*` + `!storage/*.py` +
# `!storage/migrations/*.sql`). 이 검사는 그 정밀화가 되돌아가는 것을 막는다.
#
# 검출 원리를 정확히 적어 둔다(그래야 이 검사를 과신하지 않는다).
# `git ls-files`는 **인덱스**를 읽으므로, 이미 추적 중인 파일은 `.gitignore`를 되돌려도
# 계속 추적된다. 따라서 이 검사가 실제로 잡는 것은 아래 두 가지다.
#
#   (a) 새 파일이 추적되지 않는 경우 - `.gitignore`를 `storage/`로 되돌린 뒤 새 마이그레이션
#       (019_*.sql)을 추가하면 그 파일만 조용히 빠진다. **가장 현실적인 재발 경로다**
#       (실제로 이 시나리오로 검출을 확인했다).
#   (b) 기존 파일이 추적에서 빠지는 경우 - `git rm --cached -r storage/`.
#       원래 사고가 일어난 방식이다.
#
# 둘 다 "로컬에서는 멀쩡히 동작하고 새로 clone한 환경에서만 터지는" 형태라
# 사람 눈으로는 거의 잡히지 않는다.
#
# (2026-08-13 Sprint 75에 문서 3곳의 stale 서술도 함께 정정했다.)
# ---------------------------------------------------------------------------
def test_storage_sources_are_tracked():
    print("\n--- 6. storage/ 실동작 소스가 git에 추적되는가 ---")
    import subprocess

    root = os.path.dirname(os.path.abspath(__file__))
    try:
        out = subprocess.run(["git", "ls-files", "storage/"], cwd=root,
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print("[SKIP] git을 실행할 수 없다 (%s) - 추적 검사 생략" % type(exc).__name__)
        return
    if out.returncode != 0:
        print("[SKIP] git 저장소가 아니다 - 추적 검사 생략")
        return

    tracked = {line.strip().replace("\\", "/") for line in out.stdout.splitlines() if line.strip()}

    # 디스크에 있는 실동작 소스가 전부 추적되고 있는가.
    on_disk = set()
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, "storage")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py") or fn.endswith(".sql"):
                rel = os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/")
                on_disk.add(rel)

    check_true("storage/에 소스가 존재한다", len(on_disk) > 0, on_disk)
    missing = sorted(on_disk - tracked)
    check("디스크의 storage/ 소스가 전부 추적된다", missing, [])

    # 핵심 파일은 이름으로 직접 확인한다 - 위 검사가 통째로 비어도 여기서 잡힌다.
    for must in ("storage/database.py", "storage/migrate_v4_1.py"):
        check_true("%s 가 추적된다" % must, must in tracked,
                   "추적 목록에 없다 - .gitignore가 되돌아갔는지 확인하라")

    sql_tracked = sorted(t for t in tracked if t.endswith(".sql"))
    check_true("마이그레이션 .sql이 추적된다(%d개)" % len(sql_tracked),
               len(sql_tracked) >= 18,
               "새로 clone하면 스키마를 만들 수 없다: %s" % sql_tracked)

    # 반대 방향: 데이터 산출물은 여전히 무시돼야 한다(규칙을 반대로 풀어 버리는 실수 방지).
    docs_dir = os.path.join(root, "storage", "docs")
    if os.path.isdir(docs_dir):
        leaked = sorted(t for t in tracked if t.startswith("storage/docs/"))
        check("storage/docs/(수집 산출물)는 추적되지 않는다", leaked, [])

    print("   추적 중인 storage/ 파일 %d개 (.py %d / .sql %d)"
          % (len(tracked),
             len([t for t in tracked if t.endswith(".py")]),
             len(sql_tracked)))


# ---------------------------------------------------------------------------
# 6-B. 추적 중인 파일이 미추적 파일을 import하지 않는가 (2026-08-17 Sprint 148 신설)
#
# 위 6번은 `storage/`만 본다. Sprint 148 감사에서 그 한계가 드러났다 - 신규 실동작
# 모듈 14개가 미추적이었는데 6번이 잡은 것은 마이그레이션 020 하나뿐이었다(BUGS #105).
#
# 진짜 불변식은 "새 파일이 전부 추적된다"가 아니다. 새 문서나 새 테스트가 잠시
# 미추적인 것은 무해하다. 위험한 것은 **추적 중인 파일이 미추적 파일을 import**하는
# 경우다. 이때 `git commit -a`(추적 파일만 스테이징)로 커밋하면 작업트리에서는 모든
# 테스트가 통과하는데 커밋된 트리는 ModuleNotFoundError로 부팅조차 못 한다.
#
# Sprint 148 실측: `api/v1/documents.py`(추적) -> `api/http_cache.py`(미추적) 때문에
# `import api_server`가 죽었고, 검색/상세/문서/이미지 전 기능이 동시에 정지했다.
#
# `--exclude-standard`를 쓰므로 .gitignore 대상(산출물, step*.py 등)은 애초에 후보에서
# 빠진다. 즉 이 검사가 가리키는 파일은 전부 "add하면 되는데 안 한 것"이다.
# ---------------------------------------------------------------------------
def _scan_import_edges(root, rel_files, patterns):
    r"""추적 파일들에서 `patterns` 에 해당하는 import 간선을 찾는다.

    반환: (간선 목록, 읽지 못한 파일 목록)

    **함수로 뺀 이유** (2026-08-19 Sprint 217, BUGS #146): 이 루프 안에 있던
    `encoding="utf-8"` 이 **BOM 파일의 1행 import 를 영원히 놓치고 있었다.**
    본문 맨 앞에 남는 BOM 문자는 공백이 아니라서 `^\s*(?:from|import)` 가
    매치되지 않는다. 실측: 추적 `.py` 44개가 BOM 이고 **그중 31개는 1행이 import** 다.

    이 가드는 "커밋하면 API 가 부팅되지 않는다"를 막는 P0-B 가드다(BUGS #105).
    그 가드가 BOM 파일 31개의 1행에 대해 **눈이 멀어 있었다.**

    함수 밖에 두면 회귀가 이 동작을 **직접** 시험할 수 없다 — 인코딩을 되돌려도
    "간선 0개"라는 **같은 초록**으로 보이기 때문이다. 그래서 분리했다.
    """
    edges, unreadable = [], []
    for rel in rel_files:
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            # ★ `utf-8` 이 아니라 `utf-8-sig` — 위 docstring 참고.
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                body = fh.read()
        except OSError as exc:
            # 조용히 건너뛰지 않는다. 못 읽은 파일은 "간선 없음"이 아니라 "미확인"이다.
            unreadable.append("%s (%s)" % (rel, exc))
            continue
        for rx, target, _label in patterns:
            m = rx.search(body)
            if m:
                line = body[:m.start()].count(chr(10)) + 1
                edges.append("%s:%d -> %s" % (rel, line, target))
    return edges, unreadable

def test_tracked_sources_do_not_import_untracked():
    print("\n--- 6-B. 추적 파일이 미추적 파일을 import하지 않는가 ---")
    import re
    import subprocess

    root = os.path.dirname(os.path.abspath(__file__))

    def git(*args):
        try:
            out = subprocess.run(["git"] + list(args), cwd=root,
                                 capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            return None
        return [l.strip().replace("\\", "/") for l in out.stdout.splitlines() if l.strip()]

    tracked = git("ls-files")
    untracked = git("ls-files", "--others", "--exclude-standard")
    if tracked is None or untracked is None:
        print("[SKIP] git을 실행할 수 없다 - import 간선 검사 생략")
        return

    check_true("추적 파일 목록을 읽었다", len(tracked) > 0, len(tracked))

    # 미추적 파일 중 import 대상이 될 수 있는 것만 추린다.
    py_untracked = [u for u in untracked if u.endswith(".py")]
    web_untracked = [u for u in untracked if u.endswith((".ts", ".tsx"))]

    # ★ 패턴 만드는 규칙은 **한 곳에만** 둔다 (2026-08-26, `docs/BUGS.md` #235).
    #   아래 자기 검증이 이 함수를 그대로 쓴다 — 규칙을 두 벌로 적으면 한쪽만 바뀌는 날
    #   자기 검증이 진짜 검사와 다른 것을 확인하게 된다(BUGS #224/#234 와 같은 실수).
    def _py_pattern(u):
        mod = u[:-3].replace("/", ".")                      # api/http_cache.py -> api.http_cache
        base = os.path.basename(u)[:-3]                     # -> http_cache
        pkg = mod.rsplit(".", 1)[0] if "." in mod else ""   # -> api
        alts = [re.escape(mod)]
        if pkg:
            # `from api import http_cache` / `from .http_cache import x` 형태
            alts.append(re.escape(pkg) + r"\s+import\s+[^\n]*\b" + re.escape(base) + r"\b")
            alts.append(r"\.\s*" + re.escape(base) + r"\b")
        return re.compile(r"^\s*(?:from|import)\s+[^\n]*(?:%s)" % "|".join(alts), re.M), mod

    def _web_pattern(u):
        base = os.path.basename(u).rsplit(".", 1)[0]        # ResultThumbnail
        return re.compile(
            r"""^\s*import[^\n]*from\s+['"][^'"]*/%s['"]""" % re.escape(base), re.M), base

    # 미추적 파이썬 모듈 -> 검색할 import 패턴
    patterns = []           # (정규식, 미추적파일, 설명)
    for u in py_untracked:
        rx, desc = _py_pattern(u)
        patterns.append((rx, u, desc))
    for u in web_untracked:
        rx, desc = _web_pattern(u)
        patterns.append((rx, u, desc))

    # ------------------------------------------------------------------
    # ★ 자기 검증 — 이 검사는 **미추적 소스 파일이 없으면 아무것도 하지 않는다.**
    #   지금이 정확히 그 상태다(실측: 미추적 .py/.ts/.tsx **0개**). 그때 `[PASS]` 만
    #   찍고 넘어가면 "검증했다"와 "검증할 것이 없었다"가 섞인다 — 이 저장소가
    #   `run_python_tests.py` 를 만들면서 세운 규약을 검사 안에서 어기는 셈이다.
    #
    #   그래서 **합성 입력으로 판정 규칙을 실제로 태운다.** 진짜 미추적 파일이 생기는 날
    #   이 검사가 동작한다는 것을 지금 증명해 둔다.
    # ------------------------------------------------------------------
    _rx_py, _ = _py_pattern("api/qa_ghost_module.py")
    for line, should in [
        ("from api.qa_ghost_module import x", True),
        ("import api.qa_ghost_module", True),
        ("from api import qa_ghost_module", True),
        ("from .qa_ghost_module import x", True),
        ("from api.other_module import x", False),
        ("# from api.qa_ghost_module import x", False),      # 주석은 간선이 아니다
        ("qa_ghost_module_lookalike = 1", False),
    ]:
        check("자기 검증(py): %-38r -> %s" % (line[:38], "간선" if should else "아님"),
              bool(_rx_py.search(line)), should)
    _rx_web, _ = _web_pattern("src/components/QaGhost.tsx")
    for line, should in [
        ("import QaGhost from '@/components/QaGhost'", True),
        ("import X from '@/components/Other'", False),
    ]:
        check("자기 검증(web): %-38r -> %s" % (line[:38], "간선" if should else "아님"),
              bool(_rx_web.search(line)), should)

    if not patterns:
        print("   미추적 소스 파일이 없다 - 검사할 간선 없음")
        print("   (위 자기 검증이 '미추적 파일이 생기면 잡는다'를 대신 증명한다)")
        return

    scan = [t for t in tracked if t.endswith((".py", ".ts", ".tsx"))]
    edges, unreadable = _scan_import_edges(root, scan, patterns)

    if edges:
        print("   ★ 커밋하면 깨지는 간선 %d개:" % len(edges))
        for e in edges:
            print("      %s" % e)
        print("   해소: `git add -A` 후 커밋. `git commit -a`는 미추적 파일을 빠뜨린다.")
    check("추적 파일이 미추적 파일을 import하지 않는다", sorted(edges), [])
    check("읽지 못해 검사에서 빠진 추적 파일", sorted(unreadable), [])

    # ★ **BOM 파일이 실제로 검사 대상에 들어와 있는가**를 함께 고정한다
    #   (2026-08-19 Sprint 217). 위 인코딩을 `utf-8` 로 되돌리면 BOM 파일의
    #   1행 import 를 놓치는데, 그 회귀는 "간선 0개"라는 **같은 초록**으로 보인다.
    #   그래서 열거가 아니라 **판독 능력**을 직접 검사한다.
    bom_first_import = 0
    for t in scan:
        if not t.endswith(".py"):
            continue
        try:
            with open(os.path.join(root, t.replace("/", os.sep)), "rb") as fh:
                head = fh.read(300)
        except OSError:
            continue
        if head[:3] != codecs.BOM_UTF8:
            continue
        lines = head[3:].splitlines()
        first = lines[0].decode("utf-8", "replace").strip() if lines else ""
        if first.startswith(("import ", "from ")):
            bom_first_import += 1
    check_true("BOM + 1행 import 인 추적 파일이 실제로 있다(검사가 공허하지 않다)",
               bom_first_import >= 10, bom_first_import)

    # ★ 열거가 아니라 **판독 능력**을 직접 검사한다. 인코딩을 utf-8 로 되돌리는
    #   회귀는 "간선 0개"라는 **같은 초록**으로 보이기 때문이다.
    #   `.` 는 개행에 매치되지 않으므로 `[^개행]*` 와 같다.
    probe = re.compile("^[ 	]*(?:from|import)[ 	]+.*"
                       + re.escape("qa.bom.probe"), re.M)
    probe_path = os.path.join(root, "logs", "_bom_probe.py")
    with open(probe_path, "w", encoding="utf-8-sig") as fh:
        fh.write("import qa.bom.probe" + chr(10))
    try:
        with open(probe_path, encoding="utf-8-sig", errors="replace") as fh:
            seen_sig = bool(probe.search(fh.read()))
        with open(probe_path, encoding="utf-8", errors="replace") as fh:
            seen_plain = bool(probe.search(fh.read()))
    finally:
        try:
            os.remove(probe_path)
        except OSError:
            pass
    check("BOM 파일의 1행 import 를 읽는다(utf-8-sig)", seen_sig, True)
    check("★ utf-8 로 읽으면 못 본다(이 검사가 지키는 것이 바로 그 차이다)",
          seen_plain, False)
    # ★ **스캐너를 직접 시험한다.** 위 두 검사는 "차이가 존재한다"만 보여 줄 뿐,
    #   스캔 루프가 어느 쪽을 쓰는지는 보지 않는다 — 인코딩을 되돌려도 둘 다 통과한다.
    #   (그 상태로 두면 이 검사 자체가 "함수가 있다"만 확인하는 부류가 된다.)
    #   그래서 BOM + 1행 import 인 **가짜 추적 파일**을 만들어 실제 스캐너에 먹인다.
    probe_dir = os.path.join(root, "logs")
    probe_rel = "logs/_bom_edge_probe.py"
    probe_abs = os.path.join(probe_dir, "_bom_edge_probe.py")
    with open(probe_abs, "w", encoding="utf-8-sig") as fh:
        fh.write("import qa_bom_probe_module" + chr(10) + "x = 1" + chr(10))
    try:
        fake_rx = re.compile("^[ \t]*(?:from|import)[ \t]+.*"
                             + re.escape("qa_bom_probe_module"), re.M)
        found, unread = _scan_import_edges(root, [probe_rel],
                                           [(fake_rx, "qa_bom_probe_module", "probe")])
    finally:
        try:
            os.remove(probe_abs)
        except OSError:
            pass
    check("★ 스캐너가 BOM 파일의 1행 import 를 실제로 잡는다",
          [e.split(" -> ")[1] for e in found], ["qa_bom_probe_module"])
    check("탐침 파일을 못 읽은 일은 없다", unread, [])

    # ★ **읽지 못한 파일을 조용히 삼키지 않는가.** 실제 저장소에서는 그런 파일이
    #   0개라 이 성질은 관측되지 않는다 — 즉 그냥 두면 "구현이 있다"만 확인하는 검사가
    #   된다(변이로 확인: 삼키게 만들어도 통과했다). 없는 경로를 일부러 먹여서
    #   **미확인이 미확인으로 보고되는지**를 직접 본다.
    missing_rel = "logs/_bom_edge_probe_absent.py"
    found_absent, unread_absent = _scan_import_edges(
        root, [missing_rel], [(fake_rx, "qa_bom_probe_module", "probe")])
    check("없는 파일에서 간선을 지어내지 않는다", found_absent, [])
    check_true("★ 읽지 못한 파일은 '미확인'으로 보고된다(조용히 빠지지 않는다)",
               len(unread_absent) == 1 and missing_rel in unread_absent[0],
               unread_absent)

    print("   BOM + 1행 import 인 추적 파일 %d개 / 스캔 대상 %d개"
          % (bom_first_import, len(scan)))

    print("   미추적 소스 %d개(py %d / web %d) 대상으로 추적 파일 %d개를 검사했다"
          % (len(py_untracked) + len(web_untracked),
             len(py_untracked), len(web_untracked), len(scan)))


# ---------------------------------------------------------------------------
# 6-2. `.gitignore`가 무시한다고 적어 둔 파일이 **이미 추적되고 있는가** (2026-08-13 Sprint 99)
#
# git의 ignore 규칙은 **추적을 시작한 뒤에는 적용되지 않는다.** 그래서 규칙을 나중에 추가하면
# "무시하기로 했는데 계속 따라다니는" 파일이 남고, `.gitignore`만 읽으면 정리된 것처럼 보인다.
# 의도(.gitignore)와 실제(index)가 갈라진 상태다.
#
# 실측(Sprint 99): 추적 파일 238개 중 **10개가 무시 대상**이었다.
#
#     auction.db.backup_* 9개   36.9 MB   [.gitignore:73:*.db.backup*]
#     CEO/00 CEO.txt            0.0 MB    [.gitignore:120:*.txt]
#
# **개인정보는 없다** — 9개 백업 전부를 열어 확인했고, user_id가 들어 있는 두 개도
# 전부 `qa-*` 테스트 계정이었다(실 Supabase UUID 0건). 즉 보안 문제가 아니라 저장소 위생 문제다.
# 다만 clone마다 37MB를 따라다니게 하고, "왜 여기 있는지" 아무 데도 적혀 있지 않다.
#
# **왜 지우지 않았나** — 인덱스에서 빼려면 `git rm --cached` + commit이 필요한데
# 이 세션은 commit이 금지돼 있다. 그래서 **늘어나는 것만 막는다**(이 저장소가
# `test_pipeline_integrity.py`에서 쓰는 "상한을 두고 증가만 차단" 방식과 같다).
# 새로 추가되면 즉시 실패하고, 나중에 정리해서 줄어들면 그대로 통과한다.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# OneDrive 충돌 사본 — **제품이 아니다.** 따로 센다 (2026-08-27, BUGS #253)
# ---------------------------------------------------------------------------
#
# 이 저장소에는 `<이름>-DESKTOP-DVRJEGP.<확장자>` 꼴의 파일이 8개 **추적되어** 있다.
# OneDrive 가 두 대에서 같은 파일이 바뀐 것을 보고 만든 사본이고, 실수로 커밋됐다.
# 내용은 제품 파일의 **옛 판본**이다(예: `test_crawl_orchestration-DESKTOP-DVRJEGP.py`
# 는 `upsert_batch` 의 `unchanged` 계약이 생기기 전 판본이라 KeyError 로 죽는다).
#
# 그래서 이 감사가 붉어져 있었다:
#
#     ★ 새로 추적된 SQLite DB   -> .cov_test_audit_selftests-DESKTOP-DVRJEGP_py
#     ★ 드라이버를 직접 만드는 파일 -> audit_viewport-DESKTOP-DVRJEGP.py:313
#
# 둘 다 **제품의 결함이 아니라 충돌 사본의 결함**이다. 그런데 이 사본들은 지금
# 손대지 않기로 되어 있다(정리는 사람이 판단할 일이다 — 어느 쪽이 최신인지 골라야 한다).
# 그러면 게이트가 **영원히 붉은 채**로 남고, 그 상태에서는 새로 생긴 회귀와
# 이미 아는 부채를 구별할 수 없다. `run_python_tests.py` 가 "통과와 무판정을 절대
# 합치지 않는다"고 적어 둔 것과 같은 문제다.
#
# ★ 그래서 **숨기지 않고 분리한다.** 제품 검사에서는 빼되, 아래 전용 검사가 목록을
#   그대로 찍고 **개수가 늘어나면 붉어진다.** 부채는 계속 보이고, 늘어나면 잡힌다.
ONEDRIVE_CONFLICT_RE = re.compile(r"-DESKTOP-[A-Z0-9]+(?:\.[A-Za-z0-9]+)?$|"
                                  r"-DESKTOP-[A-Z0-9]+_[A-Za-z0-9]+$")


def is_onedrive_conflict(rel):
    """`<이름>-DESKTOP-XXXX.py` / `.cov_..-DESKTOP-XXXX_py` 같은 충돌 사본인가."""
    return bool(ONEDRIVE_CONFLICT_RE.search(os.path.basename(rel)))


# 지금 알고 있는 충돌 사본 수. 늘어나면 붉어진다(줄어드는 것은 정리이므로 통과다).
KNOWN_ONEDRIVE_CONFLICTS = 8


KNOWN_TRACKED_BUT_IGNORED = {
    "CEO/00 CEO.txt",
    "auction.db.backup_20260728_103355",
    "auction.db.backup_20260728_121249",
    "auction.db.backup_20260728_123213",
    "auction.db.backup_20260730_221737",
    "auction.db.backup_20260730_221737.local",
    "auction.db.backup_before_auction_unique_20260807_095423",
    "auction.db.backup_before_court_code_20260806_173734",
    "auction.db.backup_before_migration_recovery_20260808_153510",
    "auction.db.backup_before_soft_delete_20260808_160908",
    # ★ 2026-08-27 (docs/BUGS.md #264) — 이 파일이 여기 온 경위를 남긴다.
    #
    #   `audit_test_reality.py` 가 만드는 파일별 커버리지 DB(`.cov_*`)가
    #   `.gitignore` 에 없어서 **실수로 커밋됐다.** 이번에 `.cov_*` 규칙을 넣어
    #   재발은 막았는데, 그 순간 이미 추적 중이던 이 파일이 "무시 대상인데 추적 중"이
    #   되어 여기 검사가 (정확하게) 잡았다.
    #
    #   추적을 푸는 것(`git rm --cached`)은 **하지 않았다** — 커밋을 전제로 하고,
    #   이 파일은 OneDrive 충돌 사본 정리(#253)와 함께 사람이 판단할 일이다.
    #   목록에 적어 두는 것은 "괜찮다"는 뜻이 아니라 **"알고 있고, 늘어나면 잡힌다"**
    #   는 뜻이다(위 백업 파일들과 같은 취급).
    ".cov_test_audit_selftests-DESKTOP-DVRJEGP_py",
}


# ---------------------------------------------------------------------------
# 6-3. 완전히 겹치는 인덱스가 늘고 있는가 (2026-08-13 Sprint 100)
#
# 같은 컬럼 조합에 인덱스가 둘 이상이면 **읽기 이득은 0이고** 쓰기 비용과 파일 크기만 는다.
# 이 저장소에서는 이름 규칙이 다른 두 계통이 같은 인덱스를 각각 만들면서 생겼다
# (`idx_ai_*` vs `idx_auction_item_*`) - `migrate_v4_1.py`와 마이그레이션 008/009가
# 서로를 모르고 각자 만든 결과다. "같은 것을 두 곳에서 정의한다"는 이 저장소가 계속 잡아 온 패턴.
#
# 실측(Sprint 100): **완전 중복 4쌍**, 접두 포함 7쌍.
#
#   idx_ai_auction_date               == idx_auction_item_auction_date        (auction_date)
#   idx_ai_case_no                    == idx_auction_item_case_no             (case_no)
#   idx_auction_item_minimum_bid_price== idx_minimum_bid_price                (minimum_bid_price)
#   idx_rights_summary_item_id        == idx_rs_item_id                       (item_id)
#
# **왜 지금 지우지 않나** - 현재 규모(auction_item 1,876행 / DB 5.0MB)에서 측정한 API
# p95가 전부 3.1ms 이하다. 병목이 없다. 쓰기도 하루 1회 배치라 비용이 무시할 수준이고,
# 인덱스 DROP은 스키마 변경이라 이득 없이 위험만 만든다. 측정값을 남기고 **증가만 막는다**.
#
# 접두 포함(prefix)은 대상에서 뺀다 - SQLite가 더 작은 인덱스를 고르는 편이 유리한 경우가
# 있어 의도적일 수 있다. **완전 중복은 어떤 경우에도 의도일 수 없다.**
#
# 5쌍째(2026-08-15 Sprint 121): idx_audit_logs_admin == idx_audit_logs_admin_id
# (audit_logs.admin_id). 위 4쌍과 근본 원인이 다르다 - 저 4쌍은 서로 모르는 두 마이그레이션
# 계통(`migrate_v4_1.py` vs 008/009)이 각자 만든 것이지만, `idx_audit_logs_admin_id`는
# **어떤 소스에도 없다**(`grep -rn "idx_audit_logs_admin_id"` 결과 0건 - 016번 마이그레이션은
# `idx_audit_logs_admin`만 만든다). 즉 이 인덱스는 마이그레이션을 거치지 않고 라이브 DB에
# 직접 생성됐다 - fresh clone은 이 인덱스를 갖지 않는다(순수 중복이라 동작 차이는 없다).
# 어떻게 생겼는지는 추적 불가(DB 변경 이력 없음). 드롭은 마찬가지로 스키마 변경이라 보류.
# ---------------------------------------------------------------------------
# ★ 2026-08-26 migration 021: 위 5쌍을 **전부 정리했다.** 목록을 비운다 —
#   이제 완전 중복은 **하나도 허용되지 않는다**(새로 생기면 곧바로 붉어진다).
#
#   Sprint 100이 "지금은 병목이 아니라 이득 없이 위험만 만든다"며 미룬 것을 뒤집은 근거는
#   **이득을 실제로 쟀기 때문**이다(합성 500,000행): 인덱스 생성 18.4% 단축,
#   파일 10.5%(34.9MB) 절감, API 쿼리 9종의 **실행계획 전부 SAME**, 지연 변화는 잡음 범위.
#   열 구성이 완전히 같아 플래너가 남는 쪽을 그냥 대체재로 쓴다.
#
#   접두(prefix) 중복은 이 검사의 대상이 아니고, **지워서도 안 된다** — 같은 측정에서
#   `idx_ai_sido`를 지웠더니 sido 검색이 38ms -> 244ms(+540%)가 됐다(좁은 인덱스가
#   커버링 스캔에서 읽는 페이지가 적다). 자세한 것은 021 마이그레이션 주석.
KNOWN_DUPLICATE_INDEXES = set()


def test_no_new_duplicate_indexes():
    print("\n--- 6-3. 완전히 겹치는 인덱스 ---")
    conn = dbmod.get_connection()
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]

        found = set()
        detail = []
        for t in sorted(tables):
            by_cols = {}
            for r in conn.execute("PRAGMA index_list(%s)" % t):
                name = r[1]
                if name.startswith("sqlite_autoindex"):
                    continue
                cols = tuple(c[2] for c in conn.execute("PRAGMA index_info(%s)" % name))
                by_cols.setdefault(cols, []).append(name)
            for cols, names in by_cols.items():
                if len(names) > 1:
                    found.add((t, cols))
                    detail.append("%s(%s): %s" % (t, ",".join(cols), " == ".join(sorted(names))))
    finally:
        conn.close()

    check_true("인덱스를 읽을 대상 테이블이 있다", len(tables) > 0, len(tables))

    new = sorted("%s(%s)" % (t, ",".join(c)) for t, c in (found - KNOWN_DUPLICATE_INDEXES))
    check("새로 생긴 완전 중복 인덱스 없음", new, [])

    gone = sorted("%s(%s)" % (t, ",".join(c)) for t, c in (KNOWN_DUPLICATE_INDEXES - found))
    if gone:
        print("   정리된 중복 %d건 - KNOWN_DUPLICATE_INDEXES에서 빼십시오: %s"
              % (len(gone), ", ".join(gone)))

    print("   완전 중복 %d건 (전부 알려진 항목)" % len(found))
    for d in sorted(detail):
        print("     %s" % d)


def test_no_new_tracked_but_ignored_files():
    print("\n--- 6-2. .gitignore 의도와 git index가 갈라진 파일 ---")
    root = os.path.dirname(os.path.abspath(__file__))

    try:
        ls = subprocess.run(["git", "ls-files", "-z"], cwd=root,
                            capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print("[SKIP] git을 실행할 수 없다 (%s)" % type(exc).__name__)
        return
    if ls.returncode != 0:
        print("[SKIP] git 저장소가 아니다")
        return

    tracked = [p.decode("utf-8", "replace") for p in ls.stdout.split(b"\x00") if p]
    check_true("추적 파일 목록을 얻었다", len(tracked) > 0, len(tracked))

    # `--no-index`: 추적 여부와 무관하게 "규칙만으로는 무시 대상인가"를 판정한다.
    # 경로에 공백/한글이 있어 NUL 구분자로 주고받는다(줄 단위로 하면 깨진다).
    chk = subprocess.run(["git", "check-ignore", "--no-index", "--stdin", "-z", "-v"],
                         cwd=root,
                         input=b"\x00".join(p.encode("utf-8") for p in tracked),
                         capture_output=True, timeout=60)

    fields = chk.stdout.split(b"\x00")
    offenders = set()
    for i in range(0, len(fields) - 3, 4):
        pattern = fields[i + 2].decode("utf-8", "replace")
        path = fields[i + 3].decode("utf-8", "replace")
        if not path:
            continue
        # 마지막 매칭이 부정(!) 규칙이면 무시 대상이 아니다(예: !storage/migrations/*.sql).
        if pattern.startswith("!"):
            continue
        offenders.add(path)

    new = sorted(offenders - KNOWN_TRACKED_BUT_IGNORED)
    check("새로 생긴 '무시 대상인데 추적 중'인 파일 없음", new, [])

    # 정리되면 목록에서 빼라고 알려 준다(방치되면 이 상수 자체가 낡은 정보가 된다).
    gone = sorted(KNOWN_TRACKED_BUT_IGNORED - offenders)
    if gone:
        # 콘솔 출력 문자열에는 EM DASH(U+2014)를 쓰지 않는다 - Windows cp949에서
        # UnicodeEncodeError가 난다(test_console_encoding.py가 이 규칙을 강제한다).
        print("   정리된 항목 %d개 - KNOWN_TRACKED_BUT_IGNORED에서 빼십시오: %s"
              % (len(gone), ", ".join(gone)))

    total = 0
    for p in offenders:
        full = os.path.join(root, p.replace("/", os.sep))
        if os.path.isfile(full):
            total += os.path.getsize(full)
    print("   무시 대상인데 추적 중: %d개 / %.1f MB (전부 알려진 항목)"
          % (len(offenders), total / 1048576))


# ---------------------------------------------------------------------------
# 7. 코드가 **정확성을 위해 의존하는** UNIQUE 제약 (2026-08-13 Sprint 85 신설)
#
# 세 코드 경로가 DB의 UNIQUE 제약을 "중복 방지 장치"로 직접 사용한다 — 애플리케이션에서
# 먼저 조회해 확인하지 않고, **제약 위반 예외를 받아 분기**한다(TOCTOU를 피하는 올바른 방식).
#
#     api/v1/favorites.py:add_favorite()      IntegrityError -> FAVORITE_ALREADY_EXISTS
#     api/v1/recent_items.py                  같은 (user_id,item_id)를 여러 행으로 만들지 않는다
#     api/v1/payment_logs.py:record_webhook()  event_id UNIQUE -> is_duplicate (멱등성)
#
# 즉 **제약이 사라지면 이 세 방어가 조용히 전부 무력화된다.** 중복 즐겨찾기가 쌓이고,
# 같은 PG 노티가 두 번 적용된다(결제 상태 이중 반영). 예외가 나지 않으므로 로그도 없다.
#
# 이 저장소는 그런 일이 실제로 일어날 수 있는 구조다 — migration 018이 `document_queue`를
# **테이블 재생성** 방식으로 바꿨듯이(CREATE new -> copy -> rename), 재생성 SQL에서 UNIQUE
# 한 줄을 빠뜨리면 데이터는 그대로 옮겨지고 제약만 사라진다. `test_auction_identity.py` §1이
# auction 계열 3개 테이블에 대해 같은 검사를 이미 하고 있는데, 위 세 테이블은 빠져 있었다.
# ---------------------------------------------------------------------------
def test_code_dependent_unique_constraints():
    print("\n--- 7. 코드가 의존하는 UNIQUE 제약 (Sprint 78) ---")
    import re

    # (테이블, 제약이 덮어야 하는 컬럼들, 그 제약에 의존하는 코드 경로)
    REQUIRED = [
        ("favorites", ("user_id", "item_id"),
         "api/v1/favorites.py:add_favorite() IntegrityError -> FAVORITE_ALREADY_EXISTS"),
        ("recent_items", ("user_id", "item_id"),
         "api/v1/recent_items.py 중복 행 방지"),
        ("payment_webhooks", ("event_id",),
         "api/v1/payment_logs.py:record_webhook() is_duplicate (Webhook 멱등성)"),
    ]

    conn = dbmod.get_connection()
    try:
        for table, cols, why in REQUIRED:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not row:
                check_true("%s 테이블이 존재한다" % table, False, "테이블 자체가 없다")
                continue

            ddl = row[0]
            # 주석(-- ...)을 지운 뒤 본다 — payment_webhooks의 UNIQUE 설명 주석에 'UNIQUE'라는
            # 단어가 들어 있어, 주석을 지우지 않으면 **주석만 보고 통과**할 수 있다(실측).
            ddl_no_comment = re.sub(r"--[^\n]*", " ", ddl)
            flat = " ".join(ddl_no_comment.split())

            # 테이블 레벨 UNIQUE(...) 절 + 컬럼 레벨 `col ... UNIQUE` 둘 다 인정한다.
            table_level = [m for m in re.findall(r"UNIQUE\s*\(([^)]*)\)", flat, re.IGNORECASE)]
            covered = any(
                all(c in [x.strip() for x in group.split(",")] for c in cols)
                for group in table_level
            )
            if not covered and len(cols) == 1:
                covered = re.search(
                    r"\b%s\b[^,)]*\bUNIQUE\b" % re.escape(cols[0]), flat, re.IGNORECASE
                ) is not None
            # 별도 UNIQUE INDEX로 걸어도 동등하다.
            if not covered:
                for (idx_sql,) in conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=?"
                    " AND sql LIKE '%UNIQUE%'", (table,)
                ).fetchall():
                    group = re.findall(r"\(([^)]*)\)", idx_sql or "")
                    if group and all(c in [x.strip() for x in group[0].split(",")] for c in cols):
                        covered = True
                        break

            check_true("%s: UNIQUE(%s)이 존재한다" % (table, ", ".join(cols)), covered,
                       "이 제약이 사라지면 조용히 무력화되는 방어: %s" % why)

        # ★ 제약이 **실제로 동작하는가**까지 본다. DDL 문자열만 보면 "선언은 있는데
        #   데이터에는 이미 중복이 있다"(과거에 제약 없이 쌓인 행)를 놓친다.
        for table, cols, _ in REQUIRED:
            group = ", ".join(cols)
            dup = conn.execute(
                "SELECT COUNT(*) FROM (SELECT %s FROM %s GROUP BY %s HAVING COUNT(*)>1)"
                % (group, table, group)
            ).fetchone()[0]
            check("%s: 실제 데이터에 중복 없음 (%s)" % (table, group), dup, 0)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 8. 추적 중인 소스의 BOM 상태가 HEAD와 같은가 (2026-08-13 Sprint 85 신설)
#
# 이 저장소의 소스 상당수(68개)에 UTF-8 BOM이 있고, 그것은 **의도된 현재 상태**다 —
# `test_console_encoding.py`가 그래서 읽기를 `utf-8-sig`로 고정했다.
#
# 문제는 도구가 BOM을 조용히 떨어뜨린다는 것이다. `utf-8-sig`로 읽고 `utf-8`로 다시 쓰면
# BOM이 사라진다(가장 흔한 편집 스크립트 패턴). 실제로 Sprint 78 작업 중 변이 시험 스크립트가
# `normalizer/normalizer.py`의 BOM을 떨어뜨렸고, **어떤 테스트도 그것을 잡지 못했다**
# (Python은 두 형태 모두 정상 실행하므로 회귀가 나지 않는다). 발견 경로는 `git diff`를
# 사람이 눈으로 본 것뿐이었다.
#
# 왜 문제인가 — 조용한 전량 변경은 진짜 변경을 가린다. BOM만 달라진 파일도 diff에 뜨므로,
# 리뷰에서 실제 코드 변경을 찾기 어려워지고 "이 파일을 왜 건드렸지?"가 반복된다.
# 값싼 구조로 막는다: **추적 중인 파일의 BOM 유무가 HEAD와 같아야 한다.**
#
# git이 없는 환경(배포된 tarball 등)에서는 조용히 건너뛴다 — 검사 자체가 실패 원인이 되면 안 된다.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 한글이 든 .ps1 은 **반드시** UTF-8 BOM 으로 저장돼야 한다 (2026-08-14 신설)
#
# 아래 §8은 "HEAD와 같은가"를 본다. 이건 다른 종류의 규칙이다 ― **절대 요건**이고,
# 신규 파일에도 적용되며(§8은 HEAD가 없는 새 파일을 건너뛴다), `.ps1` 은 §8의 대상 확장자도
# 아니다.
#
# 왜 절대 요건인가 ― Windows PowerShell 5.1(이 PC의 기본 `powershell.exe`)은 BOM이 없는
# `.ps1` 을 **시스템 ANSI 코드페이지(cp949)** 로 읽는다. UTF-8로 저장된 한글은 깨지고,
# 깨진 바이트가 따옴표·괄호를 삼켜 **파싱 자체가 실패한다.**
#
# 2026-08-14에 실제로 겪었다. `register_scheduler_tasks.ps1` 을 BOM 없이 저장했더니:
#
#     Unexpected token '?섏쭛' in expression or statement.
#     The string is missing the terminator: ".
#     Missing closing '}' in statement block or type definition.
#
# 스크립트가 한 줄도 실행되지 않았다. BOM 3바이트를 붙이자 그대로 정상 동작했다.
#
# 이 트랩이 특히 나쁜 이유: 편집기에서는 멀쩡해 보이고, 파일을 "고친" 사람은
# BOM을 떨어뜨렸다는 사실을 모른다(실제로 이 세션에서 `favorites.py` 의 BOM을
# 같은 방식으로 떨어뜨린 적이 있다 ― §8이 그때 잡았다).
# ---------------------------------------------------------------------------
def test_powershell_scripts_have_bom():
    print("\n--- 한글이 든 .ps1 의 UTF-8 BOM ---")
    import codecs

    root = os.path.dirname(os.path.abspath(__file__))
    BOM = codecs.BOM_UTF8

    scripts = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("node_modules", ".git", "__pycache__", ".next", ".claude")]
        scripts += [os.path.join(dirpath, f) for f in filenames if f.endswith(".ps1")]

    missing, checked = [], 0
    for path in sorted(scripts):
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            data.decode("ascii")
            continue          # 순수 ASCII 는 코드페이지와 무관하다 ― 요건 아님
        except UnicodeDecodeError:
            pass
        checked += 1
        if not data.startswith(BOM):
            missing.append(os.path.relpath(path, root).replace("\\", "/"))

    print("    .ps1 %d개 중 비ASCII 포함 %d개" % (len(scripts), checked))
    check("BOM 없는 비ASCII .ps1", missing, [])
    # ★ 하한 (2026-08-18 Sprint 205) — os.walk 나 제외 목록이 깨져 **한 개도 못 찾으면**
    #   missing 은 당연히 비고 이 검사는 조용히 통과한다. 지금 이 저장소에는 한글이 든
    #   .ps1 이 최소 1개 있다(`register_scheduler_tasks.ps1`). 0개가 되는 것은
    #   "요건이 사라졌다"가 아니라 "열거가 깨졌다"로 보는 편이 안전하다.
    check_true("검사 대상(.ps1 중 비ASCII)을 실제로 찾았다 (%d개)" % checked,
               checked >= 1, (len(scripts), checked))
    if missing:
        print("      PowerShell 5.1 이 cp949 로 읽어 파싱이 깨진다 ― BOM 3바이트를 붙일 것")


def test_source_bom_matches_head():
    print("\n--- 8. 소스 BOM 상태가 HEAD와 동일한가 (Sprint 78) ---")
    import codecs
    import subprocess

    root = os.path.dirname(os.path.abspath(__file__))
    BOM = codecs.BOM_UTF8   # b"\xef\xbb\xbf" — 리터럴로 적으면 이 파일 자체의 인코딩에 휘둘린다

    def git(*args):
        return subprocess.run(["git"] + list(args), cwd=root, capture_output=True)

    probe = git("rev-parse", "--git-dir")
    if probe.returncode != 0:
        print("[SKIP] git 저장소가 아니다(배포본) - BOM 대조 생략")
        return

    changed = git("diff", "--name-only").stdout.decode("utf-8", "replace").split()
    # 검사 대상은 **텍스트 소스**만. 바이너리/데이터는 대상이 아니다.
    exts = (".py", ".md", ".sql", ".mjs", ".ts", ".tsx", ".json", ".txt", ".css")
    targets = [f for f in changed if f.endswith(exts)]

    mismatched = []
    for rel in targets:
        head = git("show", "HEAD:" + rel)
        if head.returncode != 0:
            continue  # 새 파일 — 비교할 HEAD가 없다
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(path, "rb") as fh:
                current = fh.read(3)
        except OSError:
            continue
        if (head.stdout[:3] == BOM) != (current == BOM):
            mismatched.append(rel)

    check("작업 중 BOM이 조용히 바뀐 파일 없음", mismatched, [])
    print("   대조한 변경 소스: %d개" % len(targets))


# ---------------------------------------------------------------------------
# 9. 법원 목록(ALL_COURTS)의 무결성 (2026-08-13 Sprint 85 신설)
#
# `config/courts.py`는 커버리지 0%인 **데이터 모듈**이다. 로직이 없으니 테스트할 것도 없어
# 보이지만, 이 60줄이 곧 **매일 크롤하는 대상 전체**다. 손으로 편집하는 목록이라 값이 깨지는
# 방식이 정해져 있다.
#
#     code 중복      -> 그 법원을 두 번 돌고, DB 식별키가 (court_code, case_no, item_no)라
#                       두 번째 크롤이 첫 번째를 UPDATE한다(BUGS #18과 같은 계열의 소실)
#     한 줄 삭제     -> 그 법원 물건이 조용히 사라진다. 검색 결과가 줄어드는 것 말고 신호가 없다
#     region 오타    -> `get_courts_by_region()`이 빈 목록을 돌려주고, 지역별 실행이 0건이 된다
#
# 이 저장소는 `code == name`(둘 다 한글 법원명)이라는 실측된 전제 위에 서 있다
# (`api/v1/documents.py` 주석, `document_queue.court_code`에 한글이 들어가는 이유).
# 그 전제까지 함께 고정한다 — 코드 체계를 바꾸려면 이 검사가 먼저 실패해야 한다.
#
# 개수(60)를 박아 두는 이유: 법원을 추가/제거하는 것은 **운영 결정**이라 조용히 일어나면
# 안 된다. 의도적으로 바꿀 때 이 숫자를 함께 고치게 만든다(문서 6곳이 "60개 법원"을 말한다).
# ---------------------------------------------------------------------------
def test_court_list_integrity():
    print("\n--- 9. ALL_COURTS 무결성 (Sprint 78) ---")
    from config.courts import ALL_COURTS, get_courts_by_region
    from config.settings import SIDO_LIST
    from config.settings import COURTS as SETTINGS_COURTS

    codes = [c.code for c in ALL_COURTS]
    names = [c.name for c in ALL_COURTS]

    check("법원 수가 60개다(변경은 운영 결정 ― 함께 갱신할 것)", len(ALL_COURTS), 60)
    check("code 중복 없음", len(codes) - len(set(codes)), 0)
    check("name 중복 없음", len(names) - len(set(names)), 0)
    check("빈 값 없음", [c for c in ALL_COURTS if not (c.code and c.name and c.region)], [])
    # 이 저장소의 실측된 전제 — DB의 court_code 컬럼에 한글 법원명이 들어가는 이유다.
    check("code == name (한글 법원명 체계)", [c.code for c in ALL_COURTS if c.code != c.name], [])
    check("region이 전부 SIDO_LIST 안에 있다",
          sorted({c.region for c in ALL_COURTS if c.region not in SIDO_LIST}), [])

    # 조회 함수가 목록과 어긋나지 않는가 — 지역별 실행 경로가 이것에 의존한다.
    grouped = sum(len(get_courts_by_region(r)) for r in sorted({c.region for c in ALL_COURTS}))
    check("지역별 조회의 합이 전체와 같다(누락/중복 없음)", grouped, len(ALL_COURTS))
    check("없는 지역은 빈 목록", get_courts_by_region("없는지역"), [])

    # ------------------------------------------------------------------
    # ★ 시도 어휘가 **세 곳**에 복사돼 있다 (2026-08-26, `docs/BUGS.md` #230)
    #
    #   config/settings.py SIDO_LIST    위 검사가 ALL_COURTS.region 의 기준으로 쓴다
    #   src/app/search/SearchForm.tsx   **화면이 실제로 사용자에게 보여 주는 목록**
    #   normalizer.SIDO_PATTERNS        백엔드가 주소에서 알아볼 수 있는 어휘
    #
    #   셋을 묶는 검사가 하나도 없었다. 화면에만 시도를 하나 더하면 어떻게 되는지 쟀다:
    #
    #       extract_sido("존재하지않는도") -> ''  (못 알아본다)
    #       api/v1/search.py 는 `extract_sido(sido) or sido` 로 **원본을 그대로** 쓴다
    #       -> WHERE sido = '존재하지않는도' -> **결과 0건, 오류도 안내도 없다**
    #
    #   사용자에게는 "그 지역만 매물이 없다"로 보인다. 화면이 고를 수 있게 해 준 값인데.
    # ------------------------------------------------------------------
    import re as _re
    from normalizer.normalizer import extract_sido

    _tsx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "src", "app", "search", "SearchForm.tsx")
    try:
        tsx = open(_tsx_path, encoding="utf-8-sig").read()
    except OSError:
        tsx = ""
    check_true("SearchForm.tsx 를 읽었다(검사가 공허하지 않다)", bool(tsx), _tsx_path)
    if tsx:
        m = _re.search(r"const SIDO_LIST\s*=\s*\[(.*?)\]", tsx, _re.S)
        check_true("화면의 SIDO_LIST 를 찾았다(관용구가 바뀌면 함께 고칠 것)", bool(m), None)
        if m:
            fe = [x for x in _re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))]
            # ★ **순서는 비교하지 않는다.** 화면 목록의 순서는 드롭다운 표시 순서라
            #   UX 결정이고(현재 인구/행정 순), config 쪽은 `ALL_COURTS.region` 의
            #   membership 어휘로만 쓰인다. 처음에 순서까지 같으라고 썼다가 **멀쩡한
            #   코드를 붉게 만들었다** — 가드가 근거 없이 한쪽 순서를 강요하면
            #   사람이 가드를 끄거나 UX 를 망가뜨리게 된다. 같아야 하는 것은 **집합**이다.
            check("화면 목록과 config SIDO_LIST 가 같은 집합이다",
                  sorted(fe), sorted(SIDO_LIST))
            check("화면 목록에 중복이 없다", len(fe) - len(set(fe)), 0)

            # ★ 가장 중요한 축 — 화면이 고르게 해 준 값을 백엔드가 **알아보는가**.
            unknown = [s for s in fe if extract_sido(s) == ""]
            check("★ 화면의 모든 시도를 normalizer 가 알아본다(모르면 조용히 0건)",
                  unknown, [])
            # 정규화 결과가 자기 자신이어야 `WHERE sido = ?` 가 맞는 행을 찾는다.
            mismatched = [(s, extract_sido(s)) for s in fe
                          if extract_sido(s) and extract_sido(s) != s]
            check("화면 값이 그대로 정규화된다(다른 값으로 바뀌지 않는다)", mismatched, [])

    # 검출기 자체 검증 — 없는 시도는 정말로 못 알아봐야 이 검사에 뜻이 있다.
    check("검출기 자체 검증: 없는 시도는 normalizer 가 못 알아본다",
          extract_sido("존재하지않는도"), "")
    check("검출기 자체 검증: 아는 시도는 알아본다", extract_sido("서울"), "서울")

    # ------------------------------------------------------------------
    # ★ 위 검사들은 `ALL_COURTS` 가 **옳은가**를 본다.
    #   그런데 **크롤이 그 목록을 쓰는가**는 아무도 보지 않았다 (2026-08-26, BUGS #233).
    #
    #   `config/settings.py` 에는 `COURTS` 라는 **다른 목록**이 있다 — 서울 5개,
    #   `code="B000210"` 체계. 죽은 코드로 기록돼 있지만 **타입이 같아서**
    #   (둘 다 `List[config.settings.CourtInfo]`) `run_courts()` 에 그대로 들어간다.
    #
    #   실제로 `mvp_scraper.py` 의 import 한 줄을 바꿔 봤더니
    #   **전체 스위트가 통과했다**(2026-08-26 변이 실측). 그 상태에서 벌어지는 일:
    #
    #       크롤 대상  60개 법원 -> **5개**            (55개가 조용히 사라진다)
    #       court_code '서울중앙지방법원' -> 'B000210'  (code == name 전제가 깨진다)
    #                  -> document_queue.court_code / get_doc_dir() / 문서 서빙 경로가 전부 어긋난다
    #
    #   그래서 **크롤이 실제로 집어 드는 객체**를 여기서 못박는다.
    # ------------------------------------------------------------------
    import config.courts as _courts_mod
    import mvp_scraper as _ms

    check_true("★ 크롤이 쓰는 목록이 config/courts.py 의 ALL_COURTS 바로 그것이다",
               _ms.ALL_COURTS is _courts_mod.ALL_COURTS,
               "-> mvp_scraper 가 다른 목록(예: config/settings.py 의 COURTS)을 쓰고 있다. "
               "법원 수와 court_code 체계가 통째로 바뀐다")
    # 객체가 같더라도 **그 객체가 계약을 지키는지**는 위 검사들이 이미 본다.
    # 여기서는 크롤이 집는 쪽에도 같은 잣대를 한 번 더 댄다(새 목록으로 갈아끼우는 경우 대비).
    check("★ 크롤이 쓰는 목록의 법원 수", len(_ms.ALL_COURTS), 60)
    check("★ 크롤이 쓰는 목록도 code == name 이다",
          [c.code for c in _ms.ALL_COURTS if c.code != c.name], [])

    # settings.COURTS 는 **크롤이 쓰는 것과 달라야 한다**(같아지면 위 함정이 현실이 된 것).
    check_true("settings.COURTS 는 크롤 목록이 아니다(둘을 혼동하지 않았다)",
               _ms.ALL_COURTS is not SETTINGS_COURTS,
               "-> settings.COURTS 가 크롤에 쓰이고 있다")

    # ★ 모듈 변수만 보면 **호출부에서 잘라 쓰는 것**을 놓친다.
    #   변이 `run_courts(ALL_COURTS[:5], ...)` 가 위 검사들을 그대로 통과했다(실측) —
    #   모듈의 ALL_COURTS 는 여전히 60개 그대로이기 때문이다.
    #   그래서 **실제로 넘기는 인자**를 구문 트리로 본다. 슬라이스/필터가 끼면 잡힌다.
    import ast as _ast2
    _ms_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "mvp_scraper.py"), encoding="utf-8-sig").read()
    _calls = [n for n in _ast2.walk(_ast2.parse(_ms_src))
              if isinstance(n, _ast2.Call)
              and (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) == "run_courts"]
    check_true("run_courts 호출을 찾았다(검사가 공허하지 않다)", len(_calls) >= 1, len(_calls))
    _bad_args = []
    for _c in _calls:
        if not _c.args:
            _bad_args.append("인자 없음")
            continue
        a = _c.args[0]
        # 통과하는 것은 **맨 이름 `ALL_COURTS`** 하나뿐이다.
        if not (isinstance(a, _ast2.Name) and a.id == "ALL_COURTS"):
            _bad_args.append(_ast2.dump(a)[:60])
    check("★ run_courts 에 넘기는 것이 자르지 않은 ALL_COURTS 그대로다", _bad_args, [])

    # 검출기 자체 검증 — 슬라이스/다른 이름을 실제로 가려내는가.
    def _first_arg_ok(code):
        c = next(n for n in _ast2.walk(_ast2.parse(code))
                 if isinstance(n, _ast2.Call)
                 and (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) == "run_courts")
        a = c.args[0]
        return isinstance(a, _ast2.Name) and a.id == "ALL_COURTS"
    check("검출기 자체 검증: 맨 이름은 통과", _first_arg_ok("run_courts(ALL_COURTS, o)"), True)
    check("검출기 자체 검증: 슬라이스는 잡는다", _first_arg_ok("run_courts(ALL_COURTS[:5], o)"), False)
    check("검출기 자체 검증: 다른 이름은 잡는다", _first_arg_ok("run_courts(COURTS, o)"), False)
    check("검출기 자체 검증: 필터도 잡는다",
          _first_arg_ok("run_courts([c for c in ALL_COURTS if c.region=='서울'], o)"), False)


def _old_schema_ddl():
    """현재 DDL에서 **나중에 추가된 것들을 빼서** 옛 스키마를 만든다.

    옛 DDL을 이 파일에 복사해 두면 현재 DDL이 바뀔 때 같이 낡아버린다(그러면 검사는
    통과하지만 실제 마이그레이션 경로와는 무관한 것을 검사하게 된다). 그래서 살아 있는
    상수에서 파생시킨다 ― init_db()가 보완하려는 차이만 정확히 되돌린다.
    """
    auction = dbmod.CREATE_TABLE_SQL
    for col in ("has_spec_pdf", "has_status_doc", "has_appraisal_pdf"):
        auction = "\n".join(l for l in auction.split("\n") if col not in l)
    # Step 9 이전 이름. 이 칼럼에 담긴 값이 RENAME으로 보존되는지가 이 검사의 핵심이다.
    auction = auction.replace(
        "    created_at TEXT,", "    has_status_pdf INTEGER DEFAULT 0,\n    created_at TEXT,")

    queue = dbmod.CREATE_QUEUE_TABLE_SQL
    queue = "\n".join(l for l in queue.split("\n") if "item_no TEXT NOT NULL" not in l)
    queue = queue.replace("UNIQUE(court_code, case_no, item_no, doc_type)",
                          "UNIQUE(court_code, case_no, doc_type)")

    vlog = "\n".join(l for l in dbmod.CREATE_VERSION_LOG_TABLE_SQL.split("\n")
                     if "item_no TEXT" not in l)
    return auction, queue, vlog


def test_init_db_upgrades_old_schema():
    """init_db()의 옛 스키마 보완 분기 (2026-08-13 Sprint 85 신설).

    init_db()에는 "과거 실행분 DB"를 위한 분기가 네 개 있다 ― has_status_pdf ->
    has_status_doc RENAME, has_* 칼럼 추가, document_queue.item_no 추가,
    document_version_log.item_no 추가. 운영 DB는 이미 전부 반영된 상태라 이 분기들은
    **평소에 한 줄도 실행되지 않는다**(검사 0건이었다). 여기서 옛 스키마 DB를 픽스처로
    만들어 실제로 밟는다.

    틀렸을 때의 결과: RENAME 대신 ADD COLUMN을 하면 이미 수집한 문서 표시가 전부 0으로
    돌아가 같은 문서를 다시 받는다(크롤 부하 + 큐 소진). NOT NULL DEFAULT 없이 item_no을
    추가하면 기존 큐 행의 item_no이 NULL이 되어 (court,case,item_no) 조회에서 사라진다.

    함께 못 박는 사실 하나: init_db()는 **UNIQUE 제약을 고치지 못한다**(SQLite는 제약만
    바꾸는 ALTER가 없다). 그래서 옛 DB는 init_db() 하나로 최신 상태가 되지 않고
    migration 018이 반드시 필요하다. 이 순서를 코드로 고정해 둔다.

    변이 테스트로 확인된 것(2026-08-13): 분기 5개를 각각 없앤 변이는 모두 잡힌다. 다만
    `conn.commit()`을 지운 변이는 **잡히지 않으며, 실제로 아무 차이도 없다** ― init_db()
    본문은 전부 DDL이고 sqlite3 모듈은 DDL에 트랜잭션을 열지 않으므로 이미 확정돼 있다.
    검사를 늘려도 잡을 수 없는 종류이므로(=결함이 아니다) 그대로 둔다. 나중에 이 함수에
    DML이 들어오면 그때는 commit이 실제 의미를 갖게 되고, 그 값을 보는 검사가 필요해진다.
    """
    import shutil
    import sqlite3
    import tempfile

    print("\n--- 10. init_db() 옛 스키마 보완 분기 (Sprint 85) ---")
    auction_ddl, queue_ddl, vlog_ddl = _old_schema_ddl()
    tmpdir = tempfile.mkdtemp(prefix="qa_oldschema_")
    old_db = os.path.join(tmpdir, "old_auction.db")
    saved_path = dbmod.DB_PATH
    try:
        conn = sqlite3.connect(old_db)
        conn.execute(auction_ddl)
        conn.execute(queue_ddl)
        conn.execute(vlog_ddl)
        # 옛 DB에 이미 있던 데이터. 마이그레이션이 이걸 지키는지가 관심사다.
        conn.execute(
            "INSERT INTO auction (court_code, case_no, item_no, has_status_pdf, created_at)"
            " VALUES ('999','2026TEST9999','1',1,'2026-01-01')")
        conn.execute(
            "INSERT INTO document_queue (court_code, case_no, doc_type, status, enqueued_at)"
            " VALUES ('999','2026TEST9999','spec','pending','2026-01-01')")
        conn.execute(
            "INSERT INTO document_version_log (court_code, case_no, doc_type, new_hash)"
            " VALUES ('999','2026TEST9999','spec','abc')")
        conn.commit()
        conn.close()

        dbmod.DB_PATH = old_db
        # init_db()가 예외로 죽으면 그건 **결함**이지 테스트 오류가 아니다. 그대로 터지게
        # 두면 크래시가 되어 FAIL 집계에서 사라진다(변이 테스트에서 실제로 그렇게 나왔다:
        # RENAME 후 칼럼 목록을 갱신하지 않는 변이가 "duplicate column name"으로 죽었다).
        def try_init(label):
            try:
                dbmod.init_db()
                return True
            except Exception as exc:
                check_true("init_db()가 예외 없이 끝난다 (%s)" % label, False, repr(exc))
                return False

        upgraded = try_init("옛 스키마")

        conn = sqlite3.connect(old_db)
        conn.row_factory = sqlite3.Row
        cols = [r[1] for r in conn.execute("PRAGMA table_info(auction)").fetchall()]
        check_true("has_status_doc로 개명됐다", "has_status_doc" in cols, cols)
        check_true("옛 이름 has_status_pdf는 남지 않는다", "has_status_pdf" not in cols, cols)
        for col in ("has_spec_pdf", "has_appraisal_pdf"):
            check_true("%s 칼럼이 추가됐다" % col, col in cols, cols)

        # 없는 칼럼을 sqlite3.Row로 읽으면 IndexError로 **테스트가 죽는다** ― 그러면 결함이
        # FAIL이 아니라 크래시로 나타나 집계에서 사라진다(변이 테스트로 확인한 하네스 결함
        # 유형이다). 칼럼 부재를 값처럼 다뤄 항상 FAIL로 보이게 한다.
        def val(row, name):
            return row[name] if name in row.keys() else "<칼럼 없음>"

        row = conn.execute(
            "SELECT * FROM auction WHERE case_no='2026TEST9999'").fetchone()
        check("이미 수집된 표시(1)가 RENAME으로 보존된다", val(row, "has_status_doc"), 1)
        check("새로 추가된 칼럼은 0으로 채워진다",
              (val(row, "has_spec_pdf"), val(row, "has_appraisal_pdf")), (0, 0))

        qrow = conn.execute("SELECT * FROM document_queue").fetchone()
        check("큐의 기존 행에 item_no이 '1'로 채워진다(NULL이 아니다)", val(qrow, "item_no"), "1")
        vcols = [r[1] for r in conn.execute("PRAGMA table_info(document_version_log)").fetchall()]
        check_true("이력 로그에 item_no이 추가됐다", "item_no" in vcols, vcols)
        vrow = conn.execute("SELECT * FROM document_version_log").fetchone()
        check("이력 로그의 item_no은 NULL 허용이다", val(vrow, "item_no"), None)

        # UNIQUE 제약은 그대로다 ― 이것이 migration 018이 따로 있는 이유다.
        # enqueue는 INSERT OR IGNORE를 쓰므로, 이 상태의 DB에서는 같은 사건의 물건번호 2번이
        # **조용히 버려진다**(에러도 안 난다). init_db()만으로 끝났다고 믿으면 안 된다.
        queue_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='document_queue'"
        ).fetchone()["sql"]
        check_true("init_db()는 UNIQUE 제약을 고치지 못한다(측정된 한계)",
                   "UNIQUE(court_code, case_no, doc_type)" in queue_sql, queue_sql)
        mig = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "storage", "migrations", "018_document_queue_item_no_unique.sql")
        check_true("그 한계를 메우는 migration 018이 존재한다", os.path.exists(mig), mig)
        conn.close()

        # 두 번 실행해도 안전한가 ― 부트스트랩은 매 실행 호출된다.
        try_init("두 번째 실행")
        conn = sqlite3.connect(old_db)
        conn.row_factory = sqlite3.Row
        check("두 번째 init_db() 후에도 칼럼 수가 같다",
              len([r[1] for r in conn.execute("PRAGMA table_info(auction)").fetchall()]),
              len(cols))
        row = conn.execute("SELECT * FROM auction WHERE case_no='2026TEST9999'").fetchone()
        check("두 번째 init_db()가 값을 되돌리지 않는다", row["has_status_doc"], 1)
        conn.close()

        # 신규 DB(옛 칼럼이 아예 없는 경우)에서는 처음부터 올바른 제약으로 만들어진다.
        fresh = os.path.join(tmpdir, "fresh.db")
        dbmod.DB_PATH = fresh
        check_true("옛 스키마 보완이 예외 없이 끝났다", upgraded, "위 FAIL 참고")
        try_init("신규 DB")
        conn = sqlite3.connect(fresh)
        fresh_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='document_queue'"
        ).fetchone()[0]
        check_true("신규 DB의 큐 UNIQUE에는 item_no이 들어 있다",
                   "UNIQUE(court_code, case_no, item_no, doc_type)" in fresh_sql, fresh_sql)
        fresh_cols = [r[1] for r in conn.execute("PRAGMA table_info(auction)").fetchall()]
        check_true("신규 DB에도 has_status_doc이 있다", "has_status_doc" in fresh_cols, fresh_cols)
        check_true("신규 DB에 옛 이름은 없다", "has_status_pdf" not in fresh_cols, fresh_cols)
        conn.close()
    finally:
        dbmod.DB_PATH = saved_path
        shutil.rmtree(tmpdir, ignore_errors=True)
    check("운영 DB 경로가 원래대로 복원됐다", dbmod.DB_PATH, saved_path)


def test_init_db_failure_is_loud():
    """init_db()가 실패할 때 **조용히 넘어가지 않는가** (2026-08-13 Sprint 85 신설).

    `init_db()`의 `except Exception` 절(로그 + 재전파)이 유일하게 남은 미커버 구간이었다.
    이 절이 하는 일은 하나뿐이지만 그 하나가 중요하다 ― 부트스트랩 실패를 삼키면 이후 모든
    작업이 "테이블이 없다"는 엉뚱한 오류로 실패하고, 진짜 원인(디스크/권한/파일 손상)은
    어디에도 남지 않는다. 이 저장소가 반복해 지킨 원칙("조용히 넘기면 추적할 수 없다")이
    부트스트랩에도 적용되는지 확인한다.

    재현 방법: DB 파일 자리에 **DB가 아닌 파일**을 둔다. sqlite3는 연결 자체는 성공하고
    (지연 열기) 첫 DDL에서 `DatabaseError: file is not a database`로 실패한다 ― 디스크 손상과
    같은 계열의 실패를 파일 하나로 만들 수 있다.
    """
    import logging
    import shutil
    import tempfile

    print("\n--- 12. init_db() 실패는 조용하지 않다 (Sprint 85) ---")
    tmpdir = tempfile.mkdtemp(prefix="qa_initfail_")
    broken = os.path.join(tmpdir, "not_a_database.db")
    with open(broken, "wb") as fh:
        fh.write("이건 SQLite 파일이 아니다".encode("utf-8") * 8)
    before = open(broken, "rb").read()

    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture(level=logging.ERROR)
    logger = logging.getLogger(dbmod.__name__)
    logger.addHandler(handler)
    saved_path = dbmod.DB_PATH
    try:
        dbmod.DB_PATH = broken
        raised = None
        try:
            dbmod.init_db()
        except Exception as exc:  # noqa: BLE001 - 어떤 예외든 전파돼야 한다
            raised = exc
        check_true("실패를 삼키지 않고 예외를 전파한다", raised is not None,
                   "init_db()가 조용히 끝났다")
        check_true("sqlite 계열 오류로 전파된다", isinstance(raised, sqlite3.Error), repr(raised))
        errors = [r for r in records if r.levelno >= logging.ERROR]
        check_true("ERROR 로그를 남긴다", len(errors) >= 1, records)
        if errors:
            msg = errors[0].getMessage()
            check_true("로그에 원인이 담긴다(빈 메시지가 아니다)",
                       "DB 초기화 실패" in msg and len(msg) > len("DB 초기화 실패: "), msg)
    finally:
        dbmod.DB_PATH = saved_path
        logger.removeHandler(handler)

    # 실패했다면 그 파일을 망가뜨리지 않고 그대로 두었는가 ― 남의 파일을 덮어쓰면
    # 원인 조사조차 불가능해진다.
    # 내용을 그대로 비교하면 실패 메시지가 파일 전체를 토해낸다 ― 요약값으로 본다.
    import hashlib
    check("실패한 대상 파일을 변형하지 않는다",
          hashlib.sha256(open(broken, "rb").read()).hexdigest()[:16],
          hashlib.sha256(before).hexdigest()[:16])
    shutil.rmtree(tmpdir, ignore_errors=True)
    check("운영 DB 경로가 복원됐다", dbmod.DB_PATH, saved_path)


# ---------------------------------------------------------------------------
# 목록 조회 GET 은 "HTTP 200 = 성공"이어야 한다 (2026-08-14 신설)
#
# 이 API 에는 실패 응답이 **두 형태**로 있고, 그것 자체는 의도된 상태다(§5 참고).
#
#     error_response(code,msg)  -> HTTP 200 + {success:false, error:"CODE", ...}
#     raise HTTPException(...)  -> HTTP 4xx  + {"detail": "..."}
#
# 문제는 프런트가 목록을 받는 방식이다. 아래 네 화면은 전부 이렇게 쓴다.
#
#     const result = await fetchAuthedJSON<T[]>(path, token)
#     setItems(result.data ?? [])          // <- success 를 보지 않는다
#
# 지금은 **안전하다**. 네 엔드포인트 모두 `error_response` 를 한 번도 쓰지 않아
# HTTP 200 이면 반드시 성공이기 때문이다(2026-08-14 전수 확인). 즉 `success` 확인이
# 생략된 것이 아니라 **생략해도 되는 상태**다.
#
# 그런데 그 전제는 깨지기 쉽다. 누가 이 GET 중 하나에 `error_response(...)` 를 하나만
# 추가하면 — 예컨대 "구독이 필요합니다" — 프런트는 그 응답을 **빈 목록**으로 그린다.
# 사용자는 오류 대신 "관심물건이 없습니다"를 본다. 실패가 정상 화면으로 둔갑한다.
#
# 그래서 전제를 검사로 고정한다. 이 GET 들에 `error_response` 를 넣으려면 프런트의
# 호출부도 함께 고쳐야 하고, 이 검사가 그 사실을 먼저 알려 준다.
# ---------------------------------------------------------------------------
# (파일, GET 경로) — 프런트가 success 를 보지 않고 data 만 쓰는 목록 엔드포인트
DATA_ONLY_LIST_GETS = [
    ("favorites.py", "/favorites"),
    ("recent_items.py", "/recent-items"),
    ("search_presets.py", "/search-presets"),
    ("registry.py", "/registry-requests"),
]


def test_list_gets_never_return_success_false():
    print("\n--- 12. 목록 GET 은 HTTP 200 = 성공이어야 한다 ---")
    import re

    root = os.path.dirname(os.path.abspath(__file__))
    offenders, checked = [], 0
    for fname, route in DATA_ONLY_LIST_GETS:
        path = os.path.join(root, "api", "v1", fname)
        if not os.path.exists(path):
            check_true("%s 가 존재한다" % fname, False, path)
            continue
        src = open(path, encoding="utf-8-sig").read()
        # 해당 라우트의 GET 핸들러 본문만 잘라 본다(다음 @router 데코레이터까지).
        m = re.search(r'@router\.get\(\s*["\']%s["\']' % re.escape(route), src)
        check_true("%s 의 GET %s 핸들러를 찾았다" % (fname, route), m is not None, route)
        if not m:
            continue
        start = m.end()
        nxt = src.find("@router.", start)
        body = src[start:nxt if nxt > 0 else len(src)]
        code = "\n".join(l.split("#")[0] for l in body.splitlines())
        checked += 1
        if "error_response(" in code:
            offenders.append("%s %s" % (fname, route))

    check_true("검사 대상 GET 을 실제로 찾았다", checked == len(DATA_ONLY_LIST_GETS), checked)
    check("목록 GET 이 success=false 를 돌려주지 않는다", offenders, [])
    if offenders:
        print("      프런트(favorites/recent/search-presets/mypage)는 `result.data ?? []` 만"
              " 쓰므로, 이 응답은 화면에서 **빈 목록**이 된다.")


# ---------------------------------------------------------------------------
# 뜻이 비슷한 컬럼 중 **잘못된 쪽**을 고르지 않는가 (2026-08-14 신설)
#
# `registry_credits` / `registry_credit_logs` 에는 이름이 비슷한 컬럼이 **둘** 있다.
#
#     reason_type   GRANT / DEDUCT / RESET / USAGE / EVENT / REFUND / OTHER   <- enum
#     reason        "등기부 신청 (item_id=123)"                                <- 자유 텍스트
#
# 이런 자리는 **반드시 한 번은 잘못 고른다.** 실제로 2026-08-14에 새 검사를 쓰면서
# `WHERE reason = 'REFUND'` 라고 썼다. 자유 텍스트에 그 값이 들어갈 일이 없으니
# **보상이 실제로 있어도 영원히 0으로 세는** 검사가 될 뻔했다(사본 검증에서 잡았다).
#
# 조용히 틀리는 종류라 더 나쁘다 — 예외도 안 나고 결과가 0이라 "문제 없음"처럼 보인다.
#
# 운영 코드는 지금 전부 `reason_type` 을 쓴다(전수 확인). 그 상태를 고정한다.
# 같은 이유로 `status` 에 검증 결과(PASS/FAIL)를 비교하는 것도 막는다 —
# `auction_item` 에는 `status`("유찰 2회")와 `validation_status`("PASS"/"FAIL")가 함께 있다.
# ---------------------------------------------------------------------------
CREDIT_REASON_ENUM = ("GRANT", "DEDUCT", "RESET", "USAGE", "EVENT", "REFUND", "OTHER")


def test_no_confusable_column_misuse():
    print("\n--- 13. 뜻이 비슷한 컬럼을 잘못 고르지 않는가 ---")
    import re
    import subprocess

    root = os.path.dirname(os.path.abspath(__file__))

    # ★ 2026-08-17 Sprint 178: 미추적 파일도 검사한다.
    #
    # `git ls-files` 만으로는 아직 add되지 않은 실동작 모듈이 통째로 빠진다. 이 저장소는
    # 지금 실제로 그런 상태이고(`api/v1/images.py` / `api/http_cache.py` /
    # `crawler/image_crawler.py` 등이 미추적인데 프로덕션이 import한다), 그 파일들이
    # 이 검사에서 빠져 있었다. `--exclude-standard`를 함께 주므로 .gitignore 대상
    # (산출물, step*.py 등)은 여전히 빠진다 — §6-B가 쓰는 방식과 같다.
    p = subprocess.run(["git", "ls-files", "*.py"], cwd=root,
                       capture_output=True, text=True)
    p2 = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "*.py"],
                        cwd=root, capture_output=True, text=True)
    files = sorted({f for f in (p.stdout + "\n" + p2.stdout).split() if f})
    check_true("검사할 파일을 찾았다", len(files) > 10, len(files))

    # ★ 범위를 정확히 좁힌다. 처음에는 `status = "PASS"` 를 전부 잡았는데,
    #   테스트들이 **출력 라벨용 지역 변수**로 그 이름을 쓴다
    #   (`status = "PASS" if ok else "FAIL"` — DB 컬럼과 무관하다).
    #   그런 오탐을 남기면 검사가 곧 무시당한다. 그래서 두 형태만 본다:
    #     (a) SQL 문자열 안의 컬럼 비교  ... WHERE status='PASS'
    #     (b) 행에서 꺼낸 값의 비교      row["status"] == "PASS" / .status == "PASS"
    enum_alt = "|".join(CREDIT_REASON_ENUM)
    SQL_HINT = re.compile(r"\b(SELECT|WHERE|UPDATE|DELETE|AND|OR)\b", re.I)

    sql_reason = re.compile(r"(?<![\w_])reason\s*(?:=|==|!=)\s*['\"](?:%s)['\"]" % enum_alt)
    row_reason = re.compile(
        r"""(?:\[\s*['"]reason['"]\s*\]|\.reason)\s*(?:==|!=)\s*['"](?:%s)['"]""" % enum_alt)
    sql_status = re.compile(r"(?<![\w_])status\s*(?:=|==|!=)\s*['\"](?:PASS|FAIL)['\"]")
    row_status = re.compile(
        r"""(?:\[\s*['"]status['"]\s*\]|\.status)\s*(?:==|!=)\s*['"](?:PASS|FAIL)['"]""")

    hits_reason, hits_status = [], []
    for rel in files:
        path = os.path.join(root, rel)
        try:
            src = open(path, encoding="utf-8-sig").read()
        except OSError:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            code = line.split("#")[0]
            in_sql = bool(SQL_HINT.search(code))
            if row_reason.search(code) or (in_sql and sql_reason.search(code)):
                hits_reason.append("%s:%d" % (rel, i))
            if row_status.search(code) or (in_sql and sql_status.search(code)):
                hits_status.append("%s:%d" % (rel, i))

    check("크레딧 enum 을 자유 텍스트 reason 과 비교하지 않는다", hits_reason, [])
    check("검증 결과(PASS/FAIL)를 status 와 비교하지 않는다", hits_status, [])
    print("    %d개 파일에서 reason/reason_type · status/validation_status 사용을 대조" % len(files))


LEGACY_DOC_FLAGS = ("has_spec_pdf", "has_status_doc", "has_appraisal_pdf")


def test_api_never_reads_legacy_doc_flags():
    """화면 경로는 `auction.has_*` 플래그를 읽지 않는다 (2026-08-13 Sprint 85 신설).

    2026-08-13 실측 ― 레거시 플래그와 화면 테이블(`document_status`)이 어긋난 행이 35건이고,
    **어긋난 35건 모두 디스크 실물과 일치하는 쪽은 document_status였다**:

        SPEC        플래그=1인데 READY 아님 1건 (파일 없음)  / READY인데 플래그=0 1건 (파일 있음)
        APPRAISAL   같은 물건에서 같은 모양 1건 / 1건
        STATUS      플래그=1인데 READY 아님 33건 (전부 파일 없음)

    즉 플래그는 과거에 잘못 세워진 채 남아 있다(2026-08-11 Sprint 55, docs/BUGS.md #50에서
    화면 테이블을 디스크 기준으로 1회 보정하고, 이후 수집은 `mark_queue_done()`이 두 곳을
    한 트랜잭션에서 함께 갱신하도록 고쳤다). 지금은 `api/` 어디에서도 이 플래그를 읽지
    않는다 ― 그래서 사용자에게는 문제가 보이지 않는다.

    이 검사는 그 상태를 고정한다. 누군가 편의상 `auction.has_spec_pdf`를 다시 읽으면
    "파일이 있는데 수집중으로 보이거나, 없는데 있다고 보이는" #50이 그대로 되살아난다.
    플래그를 지우는 것(스키마 변경)은 승인 사항이라 여기서 하지 않는다 ― 대신 읽히지
    않는다는 사실만 회귀로 지킨다.
    """
    print("\n--- 11. 화면 경로는 레거시 문서 플래그를 읽지 않는다 (Sprint 85) ---")
    root = os.path.dirname(os.path.abspath(__file__))
    api_dir = os.path.join(root, "api")
    hits = []
    scanned = 0
    for dirpath, _dirs, files in os.walk(api_dir):
        if "__pycache__" in dirpath:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            scanned += 1
            with open(path, encoding="utf-8-sig") as fh:
                for lineno, line in enumerate(fh, 1):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue  # 주석에서 언급하는 것은 막을 이유가 없다
                    for flag in LEGACY_DOC_FLAGS:
                        if flag in line:
                            hits.append("%s:%d %s" % (os.path.relpath(path, root), lineno, stripped[:60]))
    check_true("api/ 소스를 실제로 읽었다(검사가 공허하지 않다)", scanned >= 5, scanned)
    check("api/ 어디서도 레거시 문서 플래그를 참조하지 않는다", hits, [])

    # 반대쪽도 확인 ― 플래그는 여전히 수집 경로에서 **쓰이고** 있다. 이게 없으면 위 검사는
    # "플래그가 아예 사라졌다"와 구별되지 않는다(그때는 이 검사 자체가 무의미해진다).
    with open(os.path.join(root, "storage", "database.py"), encoding="utf-8-sig") as fh:
        db_src = fh.read()
    for flag in LEGACY_DOC_FLAGS:
        check_true("%s는 수집 경로에 아직 존재한다" % flag, flag in db_src)


# ---------------------------------------------------------------------------
# SQL 텍스트에 새 보간이 생기면 알린다 (2026-08-14 신설)
#
# 이 API 는 WHERE 절을 **문자열로 조립한다.**
#
#     conditions.append("sigungu LIKE ?")      # 조각은 전부 상수 + ? 바인딩
#     where = " AND ".join(conditions)
#     conn.execute(f"SELECT * FROM auction_item WHERE {where}", params)
#
# 2026-08-14 실측 결과 **지금은 인젝션이 없다.** 정적/동적 양쪽으로 확인했다.
#
#   - 정적: SQL 텍스트를 만드는 보간 지점 22곳을 AST 로 전수. 요청으로 도달 가능한 7곳
#           (search 3 / admin 2 / audit 2)의 조각이 전부 **상수**이거나 상수의 반복이다.
#           유일한 f-string 조각 `f"({or_clause})"` 도 `["property_type LIKE ?"] * len(...)`
#           이라 **길이만** 가변이다. 값은 전부 `?` 로 바인딩된다.
#   - 동적: `' OR '1'='1` / `'; DROP TABLE auction_item; --` / UNION 등 6개 페이로드를
#           sido·sigungu·dong·case_no·court_name·status·address_detail·property_type 에
#           넣어 실제 요청. 전부 리터럴로 취급됐고(결과 0건), 테이블 26개와 1,876행이
#           그대로였다. 정렬 파라미터는 화이트리스트 밖이면 **HTTP 400**이다.
#
# 그러니 이 검사는 "안전함을 증명"하지 않는다 — 그건 위 실측이 이미 했다.
# 이 검사가 하는 일은 하나다: **SQL 텍스트에 새로운 보간이 들어오면 실패한다.**
#
# 지켜야 할 것이 그 지점이기 때문이다. 지금 구조에서 인젝션이 생기는 유일한 방법은
# 누가 조각 하나를 상수가 아니게 쓰는 것이다.
#
#     conditions.append(f"sido = '{sido}'")    # <- 이 한 줄이면 뚫린다
#
# 페이로드 검사는 **내가 생각해 낸 공격만** 잡지만, 이 검사는 위 한 줄을 잡는다.
# 새 보간이 정당하면 아래 목록에 추가하면 된다 — 그때 사람이 한 번 보게 하는 것이 목적이다.
# ---------------------------------------------------------------------------
# (파일, 보간되는 표현식) — SQL **텍스트**에 들어가는 것만. `f"%{x}%"` 같은
# 바인딩 **값**은 애초에 대상이 아니다(리터럴 부분에 SQL 키워드가 없다).
ALLOWED_SQL_TEXT_INTERPOLATIONS = {
    ("api/v1/search.py", "where"),          # " AND ".join(상수 조각들)
    ("api/v1/search.py", "order_clause"),   # SORT_COLUMNS 화이트리스트 + ASC/DESC
    ("api/v1/search.py", "placeholders"),   # "?,?,?" (id 개수)
    ("api/v1/admin.py", "where"),           # " AND ".join(상수 조각들)
    # 부트스트랩 스크립트의 결과 출력. 테이블명을 `sqlite_master` 가 돌려준 그대로 쓴다 —
    # DB 자신이 만든 이름이고 요청으로 도달하는 경로가 아니다.
    ("storage/migrate_v4_1.py", "t[0]"),
    # 백필 스크립트(CLI). `table` 은 호출부에서 `"auction"` / `"auction_item"` 리터럴로만
    # 넘어온다(2026-08-14 확인). 요청으로 도달하는 경로가 아니다.
    ("backfill_dong_normalize.py", "table"),
    ("backfill_dong_fix_mismatch.py", "table"),
    # 2026-08-15 Sprint 130 신설. `placeholders = ",".join(["(?,?)"] * len(case_keys))` —
    # `api/v1/search.py`의 이미 허용된 `"placeholders"`(`"?,?,?"`, id 개수)와 정확히 같은
    # 모양이다: 내용은 항상 `(?,?)` 문자만 반복되고 개수만 가변, 값은 전부 `?` 로 바인딩된다
    # (N+1 쿼리 제거, docs/SPRINT130_MIGRATE_EXECUTE_N_PLUS_1.md). 요청으로 도달하는
    # 경로가 아니라 일일 배치 스크립트다.
    ("migrate_execute.py", "placeholders"),
    # 2026-08-20 Sprint 224 신설. `api/v1/search.py` 의 이미 허용된 `placeholders` 를
    # 그대로 옮겨 온 것이다(대표 사진 배치 조회를 세 화면이 공유하게 하면서 모듈로 분리).
    # 내용은 항상 `?` 문자만 반복되고 개수만 가변, 값은 전부 `?` 로 바인딩된다.
    ("api/v1/thumbnails.py", "placeholders"),
}
# ★ 문자열 `+` 연결도 SQL 텍스트를 만든다 (2026-08-14 추가).
#
#   처음 이 검사를 만들 때 f-string 과 %-포맷만 봤다. **세 번째 형태를 통째로 놓쳤다** —
#   `storage/database.py:get_auctions()` 와 `api/v1/admin.py` 의 목록 3개가 그 형태다.
#
#       "SELECT * FROM payments WHERE " + where + " ORDER BY ..."
#       "SELECT * FROM auction " + where + " ORDER BY auction_date DESC LIMIT ?"
#       "UPDATE auction SET " + col + "=1 WHERE ..."
#
#   즉 인벤토리가 22곳이라고 적어 뒀는데 실제로는 그보다 많았다. 다시 세어 전부 확인했다:
#   조각은 여전히 전부 상수이고 값은 `?` 로 바인딩되며, `col` 은 3개 리터럴 dict 조회
#   (모르는 키는 `KeyError` 로 막힌다)라 **인젝션은 없다**. 빠졌던 것은 검사 범위다.
ALLOWED_SQL_CONCAT_OPERANDS = {
    ("api/v1/admin.py", "where"),                    # " AND ".join(상수 조각들)
    ("api/v1/admin.py", "base"),                     # 상수 SELECT 문
    ("storage/database.py", "where"),                # " AND ".join(상수 조각들)
    ("storage/database.py", "' AND '.join(conditions)"),
    ("storage/database.py", "col"),                  # 3개 리터럴 dict 조회 (KeyError 로 fail-closed)
    ("storage/database.py", "_NOW_LOCAL"),           # 모듈 상수 "datetime('now','localtime')"
    ("storage/database.py", "str(RETRY_INTERVAL_MINUTES)"),   # 모듈 상수 int
    # 2026-08-18 Sprint 189: 큐 상태 어휘가 늘어(pending/refresh) `IN (...)` 이 필요해졌다.
    # 이 상수는 **`?` 반복만** 담는다(`", ".join("?" * len(QUEUE_CLAIMABLE_STATUSES))`) —
    # 상태 값 자체는 SQL 문자열에 절대 들어가지 않고 예외 없이 바인딩된다.
    # `api/v1/payments.py`의 `... WHERE id IN (%s)`와 같은 패턴이다.
    ("storage/database.py", "QUEUE_CLAIMABLE_PLACEHOLDERS"),
    # 2026-08-18 Sprint 191: `save_auction_images()` 의 옛 행 정리를
    #   `seq > max_seq` -> `seq NOT IN (...)` 로 바꾸면서 생겼다(BUGS #127 —
    #   가운데 순번이 빠지는 경우를 `>` 비교가 못 잡았다).
    #   `placeholders` 는 `", ".join("?" * len(saved_seqs))` 로 **`?` 반복만**
    #   담는다. seq 값 자체는 SQL 문자열에 들어가지 않고 전부 바인딩된다.
    ("storage/database.py", "placeholders"),
    # 2026-08-27 BUGS #256: `upsert_batch()` 가 한 문장 upsert 로 바뀌면서 생겼다.
    #   둘 다 **모듈 상수 `UPSERT_COMPARE_COLUMNS`(리터럴 튜플)로만** 조립된다:
    #       _UPSERT_SET   = ", ".join("%s=excluded.%s" % (c, c) for c in ...)
    #       _UPSERT_WHERE = " OR ".join("auction.%s IS NOT excluded.%s" % (c, c) for c in ...)
    #   값은 하나도 들어가지 않는다(전부 `?` 바인딩). 컬럼 이름을 세 곳에 손으로 적지
    #   않으려고 한 곳에서 만든 것이라, 오히려 SET/WHERE 가 갈라지는 결함을 막는다.
    ("storage/database.py", "_UPSERT_SET"),
    ("storage/database.py", "_UPSERT_WHERE"),
    # `filter/` 는 어디에도 배선되지 않은 죽은 코드지만(docs/CLAUDE.md), 조각은 상수다.
    ("filter/filter_engine.py", "where"),
    ("filter/filter_engine.py", "' AND '.join(conditions)"),
    # 2026-08-17 Sprint 178: `unlock_retry.py` 를 인자 기반으로 재작성하면서 추가됐다
    # (BUGS #107 — 예전에는 사건번호가 소스에 박혀 있었고 법원이 빠져 있었다).
    # `build_where()` 가 만드는 조각은 전부 상수 리터럴("court_code = ?" 등)이고 값은
    # 예외 없이 `?` 로 바인딩된다 — 위 `storage/database.py`/`filter_engine.py` 의
    # `where` 항목과 **같은 패턴**이다. 사용자 입력(argparse)은 조각이 아니라 params 로만 간다.
    ("unlock_retry.py", "where"),
    # SQL 이 아니다 — 진단 출력 문자열이 "[select ..." 라 키워드 매칭에 걸린다.
    ("verify_courts.py", "sel_id"),
    ("verify_courts.py", "sel_name"),
    ("verify_courts.py", "str(s_idx)"),
}
# %-포맷으로 만드는 SQL 은 좌변 템플릿 자체를 고정한다(우변은 상수 조각/`?` 반복뿐).
ALLOWED_SQL_PERCENT_TEMPLATES = {
    ("api/v1/audit.py", "SELECT COUNT(*) FROM audit_logs WHERE %s"),
    ("api/v1/audit.py",
     "SELECT * FROM audit_logs WHERE %s ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"),
    ("api/v1/payments.py", "UPDATE payment_logs SET payment_id=? WHERE id IN (%s)"),
    # 2026-08-28 마이리스트 가져오기 (api/v1/favorite_import.py:fetch_candidates).
    # 첫 `%s` 는 **모듈 상수** `_ITEM_COLUMNS`(컬럼 이름 리터럴)이고, 둘째 `%s` 는
    # `",".join("?" * len(chunk))` / `" OR ".join(["case_no LIKE ?"] * len(chunk))` --
    # 즉 **`?` 반복뿐**이다. 사용자가 붙여넣은 사건번호는 예외 없이 바인딩된다.
    ("api/v1/favorite_import.py", "SELECT %s FROM auction_item WHERE case_no IN (%s)"),
    ("api/v1/favorite_import.py", "SELECT %s FROM auction_item WHERE %s"),
    # 2026-08-31. 두 `%s` 자리에 들어가는 것은 `_marks()` 가 만드는 **`?` 반복뿐**이고,
    # 값은 모듈 상수 튜플(`_STAT_DOC_TYPES` 3개 / `_STAT_STATUSES` 2개)에서 바인딩된다.
    #   왜 리터럴을 상수로 옮겼나 — 같은 파일이 큐 상태는 이미 상수로 세고 있어
    #   (`QUEUE_STATUS_*`) 한 파일 안에서 규칙이 둘이었다. 어휘의 단일 소스는
    #   `api/constants.py` 의 DocumentType / DocumentStatus 다.
    ("api/v1/doc_stats.py",
     "SELECT doc_type, status, COUNT(*) AS cnt FROM document_status "
     "WHERE doc_type IN (%s) AND status IN (%s) GROUP BY doc_type, status"),
    ("storage/database.py", "PRAGMA foreign_keys = %s"),
    # 2026-08-26 신설. `%s` 자리에 들어가는 것은 `",".join("?" * len(MIGRATED_DOC_TYPES))`,
    # 즉 **`?` 반복뿐**이고 값은 전부 바인딩된다. `MIGRATED_DOC_TYPES` 는 모듈 상수
    # 튜플이라 요청/외부 입력이 닿지 않는다.
    #   왜 상수를 SQL 에 직접 쓰지 않았나 — 그 목록이 §3 INSERT 루프와 **같은 단일 소스**여야
    #   하기 때문이다. 리터럴로 박으면 종류가 늘 때 한쪽만 바뀌고, 그때 이 검증이 조용히
    #   틀린 답을 낸다(2026-08-26 에 `orig * 3` 하드코딩으로 정확히 그 일이 있었다).
    ("migrate_execute.py",
     "SELECT COUNT(*) FROM document_status WHERE doc_type IN (%s)"),
    # 아래는 전부 CLI 운영 스크립트다(요청으로 도달하지 않는다). 2026-08-14 확인:
    #   `%s` 자리에 들어가는 것은 호출부의 테이블 리터럴이거나 `?` 반복뿐이고,
    #   값은 예외 없이 바인딩된다. `TARGET_COLUMNS` 도 모듈 상수 튜플이다.
    ("backfill_region_normalize.py", "SELECT id, full_address, sido, sigungu FROM %s"),
    ("backfill_region_normalize.py", "UPDATE %s SET %s = ? WHERE id = ?"),
    # 2026-08-15 Sprint 121 신설, 같은 이유 - %s 자리는 호출부 리터럴("auction"/"auction_item")뿐,
    # --apply 자체가 없어 UPDATE 경로도 없다(탐지 전용).
    ("detect_stale_region_contamination_dryrun.py",
     "SELECT id, full_address, sido, sigungu, dong, lot_number FROM %s"),
    ("load_rights_data.py", "DELETE FROM rights_summary WHERE item_id IN (%s)"),
    ("load_rights_data.py",
     "DELETE FROM tenant_rights WHERE source='STATUS' AND item_id IN (%s)"),
    ("load_spec_data.py",
     "DELETE FROM tenant_rights WHERE source='SPEC' AND item_id IN (%s)"),
    # 2026-09-02 — 위 DELETE 세 문장을 **지우기 전에 세는** COUNT 짝이다
    # (`guard_mass_purge()` 에 넘길 규모를 재는 용도, BUGS #245 배선의 전제).
    # `%s` 자리에 들어가는 것은 위 DELETE 와 **글자 그대로 같은 값** —
    # `",".join("?" * len(chunk))` 즉 물음표 반복뿐이고, item_id 는 예외 없이 바인딩된다.
    # 요청이 닿지 않는 CLI 운영 스크립트라는 점도 같다.
    ("load_rights_data.py", "SELECT COUNT(*) FROM rights_summary WHERE item_id IN (%s)"),
    ("load_rights_data.py",
     "SELECT COUNT(*) FROM tenant_rights WHERE source='STATUS' AND item_id IN (%s)"),
    ("load_spec_data.py",
     "SELECT COUNT(*) FROM tenant_rights WHERE source='SPEC' AND item_id IN (%s)"),
    ("reset_failures.py",
     "SELECT COUNT(*) FROM document_status WHERE status='FAILED' AND id IN (%s)"),
    ("reset_failures.py",
     "UPDATE document_status SET status='COLLECTING', updated_at=? "
     "WHERE status='FAILED' AND id NOT IN (%s)"),
}
_SQL_KEYWORDS = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "WHERE ", "ORDER BY",
                 " FROM ", "VALUES", "SET ", "JOIN ", "GROUP BY", "PRAGMA ", "CREATE ")


def _sql_text_interpolations(root):
    """(경로, f-string 보간식) / (경로, %-템플릿) / (경로, + 연결 피연산자) 세 집합."""
    import ast

    fstr, pct, cat = set(), set(), set()
    targets = []
    # `filter/` 와 루트 스크립트도 본다 — `api`/`storage` 만 보면 SQL 을 만드는 곳을 놓친다
    # (2026-08-14: 실제로 `filter/filter_engine.py` 와 루트 스크립트가 빠져 있었다).
    for base in ("api", "storage", "crawler", "validator", "normalizer", "filter"):
        d = os.path.join(root, base)
        if not os.path.isdir(d):
            continue
        for dp, dn, fn in os.walk(d):
            dn[:] = [x for x in dn if x != "__pycache__"]
            targets += [os.path.join(dp, f) for f in fn if f.endswith(".py")]
    targets += [os.path.join(root, f) for f in os.listdir(root)
                if f.endswith(".py")
                and not f.startswith(("test_", "step", "check_", "patch_"))]

    def _flatten_add(node, out):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            _flatten_add(node.left, out)
            _flatten_add(node.right, out)
        else:
            out.append(node)

    for path in sorted(set(targets)):
        rel = os.path.relpath(path, root).replace("\\", "/")
        with open(path, "rb") as f:
            tree = ast.parse(f.read().decode("utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                lit = "".join(v.value for v in node.values
                              if isinstance(v, ast.Constant) and isinstance(v.value, str))
                if any(k in lit.upper() for k in _SQL_KEYWORDS):
                    for v in node.values:
                        if isinstance(v, ast.FormattedValue):
                            fstr.add((rel, ast.unparse(v.value)))
            elif (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)
                  and isinstance(node.left, ast.Constant)
                  and isinstance(node.left.value, str)
                  and any(k in node.left.value.upper() for k in _SQL_KEYWORDS)):
                pct.add((rel, " ".join(node.left.value.split())))
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                parts = []
                _flatten_add(node, parts)
                consts = [p for p in parts
                          if isinstance(p, ast.Constant) and isinstance(p.value, str)]
                if any(any(k in p.value.upper() for k in _SQL_KEYWORDS) for p in consts):
                    for p in parts:
                        if not (isinstance(p, ast.Constant) and isinstance(p.value, str)):
                            cat.add((rel, ast.unparse(p)[:52]))
    return fstr, pct, cat


def _names_bound_only_to_str_literals(tree):
    """이 모듈에서 **문자열 리터럴로만** 묶이는 지역 이름들.

    `for lo_sql, hi_sql, lo, hi in (("building_area >= ?", ...), ...)` 처럼
    리터럴 튜플을 풀어 담는 형태를 인정하기 위한 것이다. 같은 이름이 한 번이라도
    리터럴이 아닌 것에 묶이면 **후보에서 뺀다**(의심스러우면 통과시키지 않는다).
    """
    import ast
    ok, bad = set(), set()

    def note(target, value):
        if isinstance(target, ast.Name):
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                ok.add(target.id)
            else:
                bad.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            vals = value.elts if isinstance(value, (ast.Tuple, ast.List)) else None
            for i, el in enumerate(target.elts):
                note(el, vals[i] if vals is not None and i < len(vals) else None)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                note(t, node.value)
        elif isinstance(node, ast.For):
            # 리터럴 튜플들의 튜플/리스트를 순회하는 경우만 인정한다.
            it = node.iter
            rows = it.elts if isinstance(it, (ast.Tuple, ast.List)) else []
            if not rows:
                for n2 in ast.walk(node.target):
                    if isinstance(n2, ast.Name):
                        bad.add(n2.id)
                continue
            for row in rows:
                note(node.target, row)
    return ok - bad


# ---------------------------------------------------------------------------
# `IN (...)` 을 만드는 지점마다 **변수 상한**을 넘지 않는가 (2026-08-27, BUGS #243)
#
# SQLite 는 한 문장의 `?` 개수에 상한이 있다(`SQLITE_LIMIT_VARIABLE_NUMBER`,
# 이 환경 32,766 / 3.31 이하 기본값 999). 넘으면 느려지는 것이 아니라
# `OperationalError: too many SQL variables` 로 **실행이 죽는다.**
#
# 실제로 그것이 매일 크롤을 통째로 죽일 수 있는 자리였다 — `migrate_execute.py` 가
# `(court_code, case_no)` 쌍 전부를 한 문장에 몰아넣어, 유니크 사건 16,384건째부터
# 파이프라인 전체가 실패했다(실측: 16,383 정상 / 16,384 파손, 결과는 전 테이블 0건).
#
# 그래서 **새 지점이 생기면 사람이 한 번 판단하게** 만든다. 각 지점은 둘 중 하나여야 한다:
#   (a) 입력 크기가 구조적으로 작다 (모듈 상수, 페이지 크기 상한 등)  -> 근거를 적는다
#   (b) `chunked_for_sql()` 로 나눈다                                  -> `len(chunk)` 가 보인다
#
# 목록을 손으로 관리하는 대신 **AST 로 전수 추출**하고 인벤토리와 대조한다 —
# 이 파일의 다른 SQL 감사(`ALLOWED_SQL_*`)와 같은 방식이다.
# ---------------------------------------------------------------------------
SQL_PLACEHOLDER_SITES = {
    # (파일, len() 인자 소스) -> 왜 안전한가
    ("api/v1/payments.py", "len(log_ids)"):
        "한 결제의 payment_logs 행. 결제 1건당 로그 수는 작다(상태 전이 횟수).",
    ("api/v1/search.py", "len(ids)"):
        "한 페이지의 결과 id. `size` 가 Query(le=100) 로 막혀 있어 최대 100.",
    ("api/v1/search.py", "len(patterns)"):
        "물건종류 별칭 패턴. PROPERTY_TYPE_ALIASES 기반 모듈 상수에서 파생, 수십 개.",
    ("api/v1/thumbnails.py", "len(ids)"):
        "호출부가 넘기는 한 페이지의 물건 id. search 와 같은 상한(<=100).",
    ("load_rights_data.py", "len(chunk)"):
        "chunked_for_sql() 로 나눈 조각 (BUGS #243).",
    ("load_spec_data.py", "len(chunk)"):
        "chunked_for_sql() 로 나눈 조각 (BUGS #243).",
    ("migrate_execute.py", "len(MIGRATED_DOC_TYPES)"):
        "모듈 상수 튜플(3개).",
    ("migrate_execute.py", "len(key_chunk)"):
        "chunked_for_sql(vars_per_item=2) 로 나눈 조각 (BUGS #243).",
    ("step11_setup.py", "len(TARGET_COURTS)"):
        "일회성 조사 스크립트의 모듈 상수.",
    ("storage/database.py", "len(QUEUE_CLAIMABLE_STATUSES)"):
        "모듈 상수 튜플(2개).",
    ("storage/database.py", "len(saved_seqs)"):
        "한 물건의 사진 순번. 법원 캐러셀 장수라 수십 장 규모.",
    # 2026-08-27 (BUGS #249). 큐 쓰기 두 곳을 행 단위 UPDATE/INSERT 에서 묶음으로 바꾸면서
    # 새로 생긴 `IN (...)` 이다. 둘 다 `chunked_for_sql()` 로 나눠 넣으므로 상한에 닿지 않고,
    # `test_queue_write_batching.py` 10번이 **커넥션 변수 상한을 10으로 낮춰** 나누기가
    # 실제로 동작하는지 소량 데이터로 검증한다(대량 DB 없이 계약을 지킨다).
    ("storage/database.py", "len(chunk)"):
        "refresh_queue_priority(): chunked_for_sql(vars_per_item=1) 로 나눈 조각 (BUGS #243/#249).",
    ("storage/database.py", "len(key_chunk)"):
        "enqueue_documents() 선조회: chunked_for_sql(vars_per_item=3) 로 나눈 조각 (BUGS #243/#249).",
    # 2026-08-28 마이리스트 가져오기. 붙여넣은 사건번호는 사용자 입력이라 개수를
    # 우리가 정하지 못한다(파서 상한 500줄 x 병합 사건 구성요소). chunked_for_sql() 로 나눈다.
    ("api/v1/favorite_import.py", "len(chunk)"):
        "fetch_candidates(): chunked_for_sql(vars_per_item=1) 로 나눈 조각 (BUGS #243).",
    # 2026-08-31. 문서 통계가 세는 대상을 상수로 옮기면서 생긴 `IN (...)` 이다.
    # 입력이 **모듈 상수 튜플**(문서 종류 3 / 상태 2)이라 요청이 크기를 정하지 못한다.
    ("api/v1/doc_stats.py", "len(values)"):
        "모듈 상수 튜플(_STAT_DOC_TYPES 3개 / _STAT_STATUSES 2개). 요청이 크기를 정하지 못한다.",
}


def _placeholder_len_arg(node):
    """`"?" * len(X)` / `["(?,?)"] * len(X)` 이면 `len(X)` 의 소스를 돌려준다."""
    import ast
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Mult):
        return None
    for a, b in ((node.left, node.right), (node.right, node.left)):
        lit = None
        if isinstance(a, ast.Constant) and isinstance(a.value, str) and "?" in a.value:
            lit = a
        elif (isinstance(a, ast.List) and a.elts
              and isinstance(a.elts[0], ast.Constant)
              and isinstance(a.elts[0].value, str) and "?" in a.elts[0].value):
            lit = a
        if lit is not None:
            return ast.unparse(b)
    return None


def test_sql_placeholder_sites_are_bounded_or_chunked():
    print("\n--- `IN (...)` 변수 상한 인벤토리 (BUGS #243) ---")
    import ast
    root = os.path.dirname(os.path.abspath(__file__))
    skip_dirs = {"node_modules", ".git", "__pycache__", ".next", ".claude"}
    found = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in skip_dirs]
        for f in fn:
            if not f.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dp, f), root).replace("\\", "/")
            # 테스트 파일은 제품 경로가 아니다.
            if rel.startswith("test_") or "/test_" in rel or rel.startswith("tests/"):
                continue
            try:
                with open(os.path.join(dp, f), "rb") as fh:
                    tree = ast.parse(fh.read().decode("utf-8-sig"))
            except Exception:      # noqa: BLE001 - 파싱 못 하는 파일은 다른 검사가 잡는다
                continue
            for node in ast.walk(tree):
                arg = _placeholder_len_arg(node)
                if arg:
                    found.setdefault((rel, arg), []).append(node.lineno)

    print("    발견한 지점 %d개" % len(found))
    check_true("검사가 공허하지 않다 - 지점을 실제로 찾았다", len(found) >= 8, len(found))

    unknown = sorted(k for k in found if k not in SQL_PLACEHOLDER_SITES)
    check_true(
        "새 `IN (...)` 지점이 인벤토리에 등록돼 있다", not unknown,
        "등록되지 않은 지점: %s -- 입력 크기가 작다는 근거를 적거나 "
        "chunked_for_sql() 로 나누십시오 (BUGS #243)" % (unknown,))

    dead = sorted(k for k in SQL_PLACEHOLDER_SITES if k not in found)
    check_true("인벤토리에 죽은 항목이 없다", not dead,
               "코드에서 사라진 항목: %s" % (dead,))

    # chunked 라고 적어 둔 곳은 **실제로** chunked_for_sql 을 쓰는가 (이름만 믿지 않는다)
    for (rel, arg), why in sorted(SQL_PLACEHOLDER_SITES.items()):
        if "chunked_for_sql" not in why:
            continue
        with open(os.path.join(root, rel), "rb") as fh:
            src = fh.read().decode("utf-8-sig")
        check_true("%s: 근거대로 chunked_for_sql 을 실제로 쓴다" % rel,
                   "chunked_for_sql(" in src, rel)


def test_no_new_sql_text_interpolation():
    print("\n--- SQL 텍스트 보간 지점 고정 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    fstr, pct, cat = _sql_text_interpolations(root)

    new_c = sorted(cat - ALLOWED_SQL_CONCAT_OPERANDS)
    check_true("+ 연결 SQL 에 새 피연산자 없음", not new_c,
               "허용 목록에 없다(정당하면 ALLOWED_SQL_CONCAT_OPERANDS 에 추가): %s" % new_c)

    new_f = sorted(fstr - ALLOWED_SQL_TEXT_INTERPOLATIONS)
    check_true("f-string SQL 에 새 보간 없음", not new_f,
               "허용 목록에 없다(정당하면 ALLOWED_SQL_TEXT_INTERPOLATIONS 에 추가): %s" % new_f)
    new_p = sorted(pct - ALLOWED_SQL_PERCENT_TEMPLATES)
    check_true("%-포맷 SQL 에 새 템플릿 없음", not new_p,
               "허용 목록에 없다: %s" % new_p)

    # 목록이 실제 코드보다 앞서 나가지 않게 한다 — 지워진 지점이 남아 있으면 검사가 헐거워진다.
    gone = sorted((ALLOWED_SQL_TEXT_INTERPOLATIONS | ALLOWED_SQL_PERCENT_TEMPLATES
                   | ALLOWED_SQL_CONCAT_OPERANDS) - (fstr | pct | cat))
    check_true("허용 목록에 죽은 항목 없음", not gone, "코드에서 사라진 항목: %s" % gone)

    # 조각이 상수인지 — WHERE 조각을 모으는 리스트에 상수 아닌 것이 들어가면 알린다.
    # (`f"({or_clause})"` 는 상수의 반복이라 예외로 둔다. 위 주석의 실측 근거 참고.)
    import ast
    # ★ 대상 파일을 손으로 적지 않는다 (2026-08-14 정정).
    #   처음에는 3개를 박아 뒀는데 `conditions.append` 를 쓰는 파일은 **5개**였다
    #   (`storage/database.py` / `filter/filter_engine.py` 가 빠져 있었다).
    #   Sprint 109·116·118 에서 반복해 고친 것과 같은 모양이라 여기서도 코드에서 유도한다.
    cond_files = []
    for base in ("api", "storage", "filter"):
        d = os.path.join(root, base)
        for dp, dn, fn in os.walk(d):
            dn[:] = [x for x in dn if x != "__pycache__"]
            for f_ in fn:
                if not f_.endswith(".py"):
                    continue
                p = os.path.join(dp, f_)
                with open(p, "rb") as fh:
                    if b"conditions.append" in fh.read():
                        cond_files.append(os.path.relpath(p, root).replace("\\", "/"))
    cond_files = sorted(set(cond_files))
    print("    conditions.append 사용 파일 %d개: %s" % (len(cond_files), ", ".join(cond_files)))
    check_true("WHERE 조각을 모으는 파일을 실제로 찾았다", len(cond_files) >= 4, cond_files)

    bad = []
    for rel in cond_files:
        with open(os.path.join(root, rel), "rb") as f:
            tree = ast.parse(f.read().decode("utf-8-sig"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "conditions"):
                continue
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                continue
            if isinstance(arg, ast.Name) and arg.id in ("addr_sql",):
                continue          # _address_condition() 이 돌려주는 상수 조각
            # `f"({or_clause})"` / `f"({area_clause})"` 만 예외.
            # 따옴표 종류에 흔들리지 않게 **구조로** 본다.
            # (`or_clause` 는 `["property_type LIKE ?"] * len(...)` ― 길이만 가변이다.)
            # (`area_clause` 는 면적 계열 OR ― 조각이 전부 소스 리터럴이고 개수만 가변이다.
            #  2026-08-26 `docs/BUGS.md` #239. 아래 CONSTANT_CLAUSE_SOURCES 가
            #  "정말 리터럴만 들어가는가"를 따로 못박는다 — 이름만 믿지 않는다.)
            if isinstance(arg, ast.JoinedStr):
                names = [ast.unparse(v.value) for v in arg.values
                         if isinstance(v, ast.FormattedValue)]
                lits = "".join(v.value for v in arg.values
                               if isinstance(v, ast.Constant) and isinstance(v.value, str))
                if names in (["or_clause"], ["area_clause"]) and lits == "()":
                    continue
            bad.append("%s:%d %s" % (rel, node.lineno, ast.unparse(arg) if arg else "?"))
    check_true("WHERE 조각이 전부 상수", not bad,
               "상수가 아닌 조각은 값이 SQL 텍스트가 된다: %s" % bad)

    # ── 위 예외가 **이름만 믿는 것**이 되지 않게 한다 (2026-08-26, `docs/BUGS.md` #239)
    #
    # `f"({or_clause})"` / `f"({area_clause})"` 를 통과시켰으니, 그 변수에 실제로 무엇이
    # 들어가는지도 봐야 한다. 안 그러면 누군가 `area_clause` 라는 이름만 유지한 채
    # 컬럼명을 f-string 으로 조립해도 이 검사가 초록으로 남는다 — 예외가 곧 구멍이 된다.
    #
    # 규칙: 그 두 변수의 재료를 모으는 리스트(`clauses`)에 append 되는 값은 **문자열 리터럴**
    #       이어야 한다. 가변인 것은 조각의 **개수**뿐이어야 한다.
    CONSTANT_CLAUSE_SOURCES = {"api/v1/search.py": ("clauses",)}
    nonliteral = []
    for rel, listnames in CONSTANT_CLAUSE_SOURCES.items():
        with open(os.path.join(root, rel), "rb") as f:
            tree = ast.parse(f.read().decode("utf-8-sig"))
        seen = 0
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in listnames):
                continue
            seen += 1
            a = node.args[0] if node.args else None
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                continue
            # 리터럴을 담아 둔 지역 이름(예: lo_sql/hi_sql)도 허용하되, 그 이름이
            # 리터럴 튜플에서만 왔는지 확인한다.
            if isinstance(a, ast.Name) and a.id in _names_bound_only_to_str_literals(tree):
                continue
            nonliteral.append("%s:%d %s" % (rel, node.lineno,
                                            ast.unparse(a) if a else "?"))
        check_true("%s 의 조각 수집 지점을 실제로 찾았다" % rel, seen > 0, seen)
    check_true("면적/물건종류 OR 조각의 재료가 전부 문자열 리터럴", not nonliteral,
               "조립된 조각이 섞이면 예외가 구멍이 된다: %s" % nonliteral)


# ---------------------------------------------------------------------------
# 7. 마이그레이션 러너의 실패/재실행 경로 (2026-08-13 Sprint 86 신설)
#
# 커버리지가 지목했다: `storage/migrations/run_migrations.py`의 두 분기가 미커버였다.
#
#     if applied: [SKIP] continue      재실행 시 이미 적용된 것을 건너뛴다(멱등성)
#     except: [FAIL] raise             실패하면 기록하지 않고 예외를 올린다
#
# 이 파일은 `docs/CLAUDE.md`가 "safe to re-run"이라 안내하는 부트스트랩이고, 신규 clone에서
# 스키마를 만드는 유일한 경로다. 두 분기 모두 **한 번도 실행된 적이 없었다.**
#
# 두 번째가 특히 중요하다. 실패한 마이그레이션이 `migration_history`에 기록되면 재실행이
# 그것을 건너뛰어 **스키마가 영구히 깨진 채로 남는다.** 현재 구현은 INSERT 전에 raise하므로
# 기록되지 않는다 - 그 순서를 고정한다.
# ---------------------------------------------------------------------------
def test_migration_runner_skip_and_failure():
    print("\n--- 7. 마이그레이션 러너: 재실행/실패 경로 ---")
    import shutil
    import sqlite3
    import tempfile
    import storage.database as dbmod
    import storage.migrations.run_migrations as runmig

    d = tempfile.mkdtemp(prefix="qa_mig_")
    real_db, real_dir = dbmod.DB_PATH, runmig.MIGRATIONS_DIR
    try:
        mig_dir = os.path.join(d, "migrations")
        os.makedirs(mig_dir)
        dbmod.DB_PATH = os.path.join(d, "t.db")
        runmig.MIGRATIONS_DIR = mig_dir

        def write(name, sql):
            with open(os.path.join(mig_dir, name), "w", encoding="utf-8") as fh:
                fh.write(sql)

        def history():
            c = sqlite3.connect(dbmod.DB_PATH)
            try:
                return [r[0] for r in c.execute(
                    "SELECT filename FROM migration_history ORDER BY id")]
            finally:
                c.close()

        def tables():
            c = sqlite3.connect(dbmod.DB_PATH)
            try:
                return sorted(r[0] for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"))
            finally:
                c.close()

        # --- 정상 적용 ---
        write("001_a.sql", "CREATE TABLE IF NOT EXISTS qa_a (x INTEGER);")
        write("002_b.sql", "CREATE TABLE IF NOT EXISTS qa_b (y INTEGER);")
        runmig.run()
        check("두 마이그레이션이 기록된다", history(), ["001_a.sql", "002_b.sql"])
        check_true("테이블이 실제로 생겼다", {"qa_a", "qa_b"} <= set(tables()), tables())

        # --- ★ 재실행은 멱등이다 ---
        #
        # 스킵 분기가 사라지면 같은 filename을 다시 INSERT하려다 UNIQUE 제약에 걸려
        # **예외가 그대로 올라온다**(스위트 크래시). 그 형태로 끝나면 원인이 안 보이므로
        # 붙잡아 깔끔한 FAIL로 바꾼다.
        rerun_error = None
        try:
            runmig.run()
        except Exception as exc:
            rerun_error = exc
        check_true("재실행이 예외 없이 끝난다", rerun_error is None,
                   "이미 적용된 것을 건너뛰는 분기가 사라졌는가? "
                   "같은 filename 재INSERT로 UNIQUE에 걸린다: %r" % (rerun_error,))
        check("재실행해도 이력이 늘지 않는다", history(), ["001_a.sql", "002_b.sql"])

        # 새 파일만 추가로 적용된다(앞의 둘은 건너뛴다).
        write("003_c.sql", "CREATE TABLE IF NOT EXISTS qa_c (z INTEGER);")
        try:
            runmig.run()
        except Exception as exc:
            check_true("새 파일 추가 실행이 예외 없이 끝난다", False, repr(exc))
        check("새 파일만 추가된다", history(), ["001_a.sql", "002_b.sql", "003_c.sql"])

        # --- ★ 실패한 마이그레이션은 기록되지 않는다 ---
        write("004_bad.sql", "CREATE TABLE qa_d (w INTEGER);\nTHIS IS NOT SQL;")
        raised = False
        try:
            runmig.run()
        except Exception:
            raised = True
        check("실패는 예외로 올라온다(삼키지 않는다)", raised, True)
        check_true("실패한 파일은 이력에 없다", "004_bad.sql" not in history(), history())
        check("앞선 이력은 그대로", history(), ["001_a.sql", "002_b.sql", "003_c.sql"])

        # --- ★ 부분 적용은 이제 일어나지 않는다 (2026-08-27 정정) ---
        #
        # 예전 이 자리에는 정반대가 적혀 있었다 — *"실패해도 앞 문장은 남아 있다"* 를
        # **사실로 고정**해 두고 "019를 쓰는 사람이 알아야 하는 성질", "코드는 바꾸지
        # 않았다(실행 모델 변경은 부트스트랩 전체에 영향을 준다)"로 남겨 두었다.
        #
        # 그 판단이 뒤집힌 이유는 위험을 **실제로 재현**했기 때문이다
        # (2026-08-27 크롤->DB 경로 감사, `test_migration_atomicity.py`):
        #
        #   - `ALTER ADD COLUMN` 두 개 뒤에서 실패 -> 컬럼 둘 다 남는다. 재실행은
        #     `duplicate column name` 으로 죽는다. SQLite 에는 ADD COLUMN 용
        #     IF NOT EXISTS 가 없으므로 **가드를 쓸 수가 없다**(025 주석이 인정한다).
        #     즉 "가드 없이 쓰면"이 아니라 **가드를 쓸 수 없는 문장이 이미 있었다.**
        #   - 023/024 의 `DROP 원본` -> `RENAME` 사이에서 죽으면 **원본 테이블이
        #     사라진 채 확정**된다. 대상이 payment_webhooks / registry_credits 다.
        #   - 그 상태에서 러너가 raise -> `run_daily.bat` 3단계 exit 1 ->
        #     **mvp_scraper.py 가 아예 실행되지 않는다.** 한 번의 사고가 매일 06:00
        #     크롤을 영구히 세운다.
        #
        # "지금까지 발현된 적이 없다"는 옛 사유는 파일이 18개일 때의 이야기였고,
        # 그 뒤 021~025 가 들어오면서 **가드 불가 문장과 DROP/RENAME 이 둘 다 생겼다.**
        #
        # 고친 방법: 한 파일 + history INSERT 를 **한 트랜잭션**으로 묶는다. SQLite 는
        # MySQL/Oracle 과 달리 DDL 도 트랜잭션에 참여하므로 이것으로 충분하다.
        # (`storage/migrations/run_migrations.py` 의 적용 루프 주석 참고)
        check_true("실패한 파일은 앞 문장까지 통째로 롤백된다",
                   "qa_d" not in tables(),
                   "러너가 다시 executescript()로 돌아갔는가? %s" % tables())

        # 재실행해도 같은 지점에서 다시 실패한다 — 파일 자체가 아직 잘못됐으니 당연하다.
        # 달라진 것은 **실패의 성질**이다: 예전에는 "이미 존재한다"로 원인이 바뀌어
        # 영구히 막혔고, 이제는 매번 원래 오류로 실패하므로 파일만 고치면 풀린다.
        raised_again = False
        try:
            runmig.run()
        except Exception:
            raised_again = True
        check("잘못된 파일은 재실행에서도 실패한다", raised_again, True)
        check_true("여전히 이력에 없다", "004_bad.sql" not in history(), history())
        check_true("재실행 뒤에도 부분 적용이 없다", "qa_d" not in tables(), tables())

        # ★ 그리고 **고치면 그냥 풀린다** — 이것이 원자성으로 얻은 실제 가치다.
        #   예전 러너에서는 파일을 고쳐도 앞 문장의 잔여물 때문에 계속 막혔다.
        write("004_bad.sql", "CREATE TABLE IF NOT EXISTS qa_d (w INTEGER);")
        fixed_error = None
        try:
            runmig.run()
        except Exception as exc:
            fixed_error = exc
        check_true("고친 뒤 재실행이 성공한다", fixed_error is None, fixed_error)
        check("고친 파일이 이력에 들어간다", history(),
              ["001_a.sql", "002_b.sql", "003_c.sql", "004_bad.sql"])
    finally:
        dbmod.DB_PATH, runmig.MIGRATIONS_DIR = real_db, real_dir
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# 8. 알려진 취약점이 있는 의존성 버전이 조용히 더 나빠지지 않는가 (2026-08-15 Sprint 125)
#
# `npm audit`의 축약 출력만 보고 "전부 빌드 툴체인, 런타임 무관"이라고 결론 냈다가
# `npm audit fix --dry-run`(전체 출력)에서야 Next.js 자체의 CVE 9건을 발견했다
# (`docs/SPRINT125_NEXTJS_CVE_CORRECTION.md`). 그중 2건은 이 저장소의 실제 설정
# (App Router + Server Action, `src/app/login/actions.ts`)에 그대로 적용되고, 하나는
# CVSS 8.2 미인증 DoS로 우회책이 없다. 고치려면 `next` 버전 설치가 필요해 승인
# 영역이라 이 세션에서는 실행하지 않았다 - 대신 **적어도 더 나빠지지는 않는지**를
# 검사로 고정한다(다른 이 저장소 관례와 같은 상한/allowlist 방식).
#
# 실패 조건으로 만들지 않는다 - 지금 상태 자체가 이미 알려진 취약점이 있는 상태라
# "PASS해야 안전"이 아니라 "얼마나 뒤처졌는지 알려주는" 게 이 검사의 역할이다.
# 업그레이드되면(버전이 KNOWN_SAFE_MIN 이상이 되면) 이 검사가 스스로 알려준다.
# ---------------------------------------------------------------------------

# next@16.2.11에서 CVE-2026-64643(Server Function 노출)/CVE-2026-64641(Server
# Actions DoS, CVSS 8.2)이 고쳐졌다. 16.2.12까지 실재 확인(`npm view next versions`).
KNOWN_VULNERABLE_NEXT_VERSION = "16.2.9"
# 2026-08-18 Sprint 207 정정: 예전 값 "16.2.11" 은 **더 이상 안전선이 아니다.**
# `npm audit` 실측(같은 날)에서 next 취약 범위가 `9.3.4-canary.0 - 16.3.0-preview.10`
# 으로 넓어졌고, npm 이 제시하는 수정본은 16.3.1(isSemVerMajor=false)이었다.
# 16.2.11 로 올리면 CVE-2026-64641 하나는 벗어나도 나머지 8건이 그대로 남는다.
# 낡은 안전선을 그대로 두면 "올렸으니 됐다"는 잘못된 종결로 이어진다.
#
# ★ 2026-08-24 Sprint 251 재실측 (`npm audit --json`): 취약 범위는 그대로
#   `9.3.4-canary.0 - 16.3.0-preview.10`, 권고 9건도 그대로인데 npm 이 제시하는
#   수정본이 **16.3.2** 로 올라갔다(isSemVerMajor=false). 안전선을 따라 올린다.
KNOWN_SAFE_MIN_NEXT_VERSION = "16.3.2"

# ---------------------------------------------------------------------------
# ★ 2026-08-24 Sprint 251 — 이 저장소에서 **가장 중요한 권고는 DoS 가 아니다**
#
# 아래 안내 문구는 오랫동안 CVE-2026-64641(Server Actions 미인증 DoS, CVSS 8.2)
# 하나만 이름으로 불렀다. 오늘 `npm audit` 전체를 다시 읽으니 같은 묶음에
# 이 앱의 구조에 훨씬 직접적으로 걸리는 것이 있다:
#
#   GHSA-6gpp-xcg3-4w24  Middleware / Proxy bypass in App Router applications
#                        using Turbopack and single locale   (high, CWE-285 인가 우회)
#                        해당 범위 >=16.0.0 <16.2.11  -> 설치본 16.2.9 는 **해당된다**
#
# 왜 이 앱에 직접 걸리나 (2026-08-24 실측):
#   - 라우트 단위 인증 게이트가 `src/proxy.ts` **하나뿐**이다
#     (PROTECTED_PREFIXES = /properties, /favorites, /mypage -> 미로그인 시 307).
#   - `next dev` 배너가 "Next.js 16.2.9 (Turbopack)", i18n 설정 없음(단일 로케일).
#     즉 권고가 말하는 전제 조건과 구성이 일치한다.
#
# 다만 **데이터가 새는 것은 아니다** — 이것도 재서 확인했다:
#   - 개인 데이터는 전부 파이썬 API 가 낸다. `src/lib/api.ts` 가 Supabase
#     access_token 을 `Authorization: Bearer` 로 실어 보내고,
#   - 그 API 는 토큰 없음/쓰레기 토큰/`alg=none` 위조 토큰 세 경우 모두 **401** 이다
#     (오늘 6개 보호 라우트 x 3가지 토큰 = 18회 실측, 전부 401).
#   따라서 게이트가 뚫려도 얻는 것은 **빈 화면 껍데기**이고 사용자 데이터는 아니다.
#
# 그래도 등급을 낮추지 않는다 — 인가 경계가 설계대로 작동하지 않는 상태이고,
# 다음에 누가 화면에서 직접 데이터를 읽는 경로를 하나만 추가해도 그 순간 실피해가 된다.
# 업그레이드는 `npm install` 이 필요해 **승인 영역**이다(이 세션에서 실행하지 않았다).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 2026-08-18 Sprint 207 실측 스냅샷 (`npm audit`, moderate 1 / high 6 / 합계 7).
#
# 위 검사는 **next 하나만** 본다. 그것이 이 가드의 사각지대였다 - 나머지 6개는
# 아무도 보고 있지 않았다. 새 CVE 를 오프라인에서 알아낼 방법은 없지만,
# **설치본이 조용히 뒤로 가는 것**은 잠글 수 있다(같은 파일 8번 검사가 next 에
# 대해 이미 쓰는 방식이다).
#
# 값은 `package-lock.json` 실측이다. 올리는 것은 자유롭고, 내리면 걸린다.
# 스냅샷을 갱신할 때는 `docs/BETA_RELEASE_CHECKLIST.md` 의 같은 표도 함께 고칠 것.
# ---------------------------------------------------------------------------
ADVISORY_SNAPSHOT_2026_08_18 = {
    "next": "16.2.9",
    "sharp": "0.34.5",
    "postcss": "8.5.15",
    "nanoid": "3.3.15",
    "js-yaml": "4.3.0",
    "brace-expansion": "1.1.15",
    "@tailwindcss/postcss": "4.3.1",
}


def _parse_version_tuple(v):
    return tuple(int(p) for p in v.split(".") if p.isdigit())


def test_known_dependency_cves_are_tracked():
    print("\n--- 8. 알려진 CVE가 있는 의존성 버전 추적 (next) ---")
    import json

    root = os.path.dirname(os.path.abspath(__file__))
    pkg_path = os.path.join(root, "package.json")
    check_true("package.json이 존재한다", os.path.exists(pkg_path), pkg_path)
    if not os.path.exists(pkg_path):
        return

    with open(pkg_path, encoding="utf-8-sig") as fh:
        pkg = json.load(fh)
    next_ver = pkg.get("dependencies", {}).get("next", "")
    check_true("package.json에 next 버전이 선언돼 있다", bool(next_ver), pkg.get("dependencies"))

    cur = _parse_version_tuple(next_ver)
    known = _parse_version_tuple(KNOWN_VULNERABLE_NEXT_VERSION)
    safe_min = _parse_version_tuple(KNOWN_SAFE_MIN_NEXT_VERSION)

    # 알려진 값보다 더 낮은 버전으로 조용히 후퇴하지는 않았는가(다운그레이드 감지).
    check_true("next가 알려진 버전보다 낮게 후퇴하지 않았다(다운그레이드 감지)",
               cur >= known, "package.json next=%s, 기준=%s" % (next_ver, KNOWN_VULNERABLE_NEXT_VERSION))

    if cur < safe_min:
        print("   [알려진 취약점] next=%s 는 권고 9건에 해당한다. 이 저장소에 가장 직접적인 것:"
              % next_ver)
        print("     - GHSA-6gpp-xcg3-4w24  Middleware/Proxy bypass (high, 인가 우회, <16.2.11)")
        print("       이 앱의 라우트 인증 게이트는 src/proxy.ts 하나뿐이고 Turbopack+단일 로케일이라")
        print("       권고의 전제와 구성이 일치한다. 다만 개인 데이터는 파이썬 API 가 Bearer 토큰으로")
        print("       따로 막고 있어(실측: 무효 토큰 전부 401) 게이트가 뚫려도 새는 것은 껍데기다.")
        print("     - CVE-2026-64641  Server Actions 미인증 DoS (CVSS 8.2, 우회책 없음)")
        print("   %s 이상으로 올리면 해소된다 (docs/SPRINT125_NEXTJS_CVE_CORRECTION.md,"
              " 승인 후 `npm install next@%s`)."
              % (KNOWN_SAFE_MIN_NEXT_VERSION, KNOWN_SAFE_MIN_NEXT_VERSION))
    else:
        print("   [정리됨] next=%s는 이미 %s 이상이다 - 위 KNOWN_VULNERABLE_NEXT_VERSION/"
              "KNOWN_SAFE_MIN_NEXT_VERSION 상수와 SPRINT125 문서의 SKIP 항목을 정리하십시오."
              % (next_ver, KNOWN_SAFE_MIN_NEXT_VERSION))

    # --- 8-B. next 말고 나머지도 뒤로 가지 않는가 (2026-08-18 Sprint 207) -------
    #
    # 위 검사는 next 하나만 본다. 실측해 보니 권고가 걸린 패키지는 **7개**였고
    # 나머지 6개는 아무 검사도 받지 않고 있었다. 새 CVE 는 오프라인에서 알 수 없지만,
    # 설치본이 조용히 낮아지는 것은 여기서 잠근다.
    lock_path = os.path.join(root, "package-lock.json")
    check_true("package-lock.json이 존재한다", os.path.exists(lock_path), lock_path)
    if os.path.exists(lock_path):
        with open(lock_path, encoding="utf-8-sig") as fh:
            lock = json.load(fh)
        packages = lock.get("packages", {})
        check_true("lock에서 설치 목록을 읽었다 (%d개)" % len(packages),
                   len(packages) > 50, len(packages))

        regressed, unseen = [], []
        for pkg, pinned in sorted(ADVISORY_SNAPSHOT_2026_08_18.items()):
            entry = packages.get("node_modules/" + pkg)
            if not entry or not entry.get("version"):
                unseen.append(pkg)
                continue
            cur_v = _parse_version_tuple(entry["version"])
            if cur_v < _parse_version_tuple(pinned):
                regressed.append("%s: %s -> %s" % (pkg, pinned, entry["version"]))

        check("권고가 걸린 패키지가 스냅샷보다 낮아지지 않았다", sorted(regressed), [])
        # 사라진 것도 조용히 넘기지 않는다 - 의존성 구조가 바뀌었다는 신호이고,
        # 그러면 스냅샷 자체를 다시 떠야 한다.
        check("스냅샷의 패키지가 전부 lock에 있다", sorted(unseen), [])


def _module_level_constant_names(path):
    """UPPER_SNAKE 이름의 최상위 상수 할당(`X = ...` 또는 `X: T = ...`) 이름 집합."""
    import ast

    with open(path, encoding="utf-8-sig") as f:
        tree = ast.parse(f.read())
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id.isupper():
            names.add(node.target.id)
    return names


def test_no_duplicate_config_constants():
    """`config/settings.py`가 다른 모듈과 같은 이름의 상수를 독립적으로 다시 선언하지 않는다.

    2026-08-16 Sprint 136 ― `MAX_DOC_RETRY`/`RETRY_INTERVAL_MINUTES`(→ storage/database.py와
    중복)와 `PAGE_LOAD_TIMEOUT`/`ELEMENT_TIMEOUT`/`AJAX_TIMEOUT`(→ crawler/base_crawler.py와
    중복) 5개가 이 저장소에 실제로 존재했다 — 값은 우연히 같았지만(`config/settings.py`
    쪽은 어디서도 import되지 않는 죽은 사본), 한쪽만 바뀌면 조용히 어긋날 수 있는 구조였다.
    둘 다 죽은 사본 쪽(config/settings.py)을 지워 원본 하나로 통일했다(각 Sprint 문서 참고).
    이 검사는 같은 이름 재선언이 다시 생기면 잡는다 — "값이 우연히 같아 보이지 않는 결함"이
    재발하는 것을 막는 목적이지, 지금 상태를 봉인하는 스냅샷 검사가 아니다.
    """
    print("\n--- 9. config/settings.py 상수 중복 재선언 없음 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    settings_path = os.path.join(root, "config", "settings.py")
    check_true("config/settings.py가 존재한다", os.path.exists(settings_path), settings_path)
    if not os.path.exists(settings_path):
        return

    settings_names = _module_level_constant_names(settings_path)
    check_true("config/settings.py에서 상수를 읽었다", len(settings_names) > 0, settings_names)

    peers = ("storage/database.py", "crawler/base_crawler.py")
    overlaps = []
    for rel in peers:
        peer_path = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.exists(peer_path):
            continue
        peer_names = _module_level_constant_names(peer_path)
        shared = sorted(settings_names & peer_names)
        if shared:
            overlaps.append("%s <-> config/settings.py: %s" % (rel, shared))

    check("config/settings.py와 storage/database.py·crawler/base_crawler.py가 "
          "같은 이름의 상수를 독립적으로 재선언하지 않는다", overlaps, [])



# ---------------------------------------------------------------------------
# 14-B. config 상수와 그 "사본"이 어긋나지 않는가 (2026-08-17 Sprint 183 신설)
#
# `config/settings.py` 는 두 상수를 정의해 두고 **아무도 import하지 않는다**. 실제 값은
# 각각 다른 곳에 인라인으로 한 벌 더 적혀 있다:
#
#     DOC_TYPE_LIST         -> storage/database.py:enqueue_documents() 의 for 루프 리터럴
#     PRIORITY_REFRESH_TIME -> register_scheduler_tasks.ps1 의 Time 필드
#
# 그 파일의 주석 자신이 이렇게 적고 있다 —
# "둘 중 하나만 고치면 조용히 어긋나므로 함께 맞춰 둔다."
#
# 통합은 사유와 함께 별도 과제로 미뤄져 있다(그 주석 참고). 그렇다면 최소한
# **"함께 맞춰 둔다"를 사람의 기억이 아니라 검사가 지키게** 해야 한다. 어긋나면
# 증상이 조용하다 — 새 문서 종류를 config에 추가해도 큐에는 안 들어가고,
# 우선순위 갱신 시각을 바꿔도 스케줄러는 옛 시각으로 등록된다.
# ---------------------------------------------------------------------------
def test_config_constants_match_their_copies():
    print("\n--- 14-B. config 상수와 사본이 일치하는가 (Sprint 183) ---")
    import re

    root = os.path.dirname(os.path.abspath(__file__))

    def read(rel):
        path = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.exists(path):
            return None
        return open(path, encoding="utf-8-sig", errors="replace").read()

    cfg = read("config/settings.py")
    check_true("config/settings.py를 읽었다", bool(cfg), cfg is None)
    if not cfg:
        return

    # --- (1) DOC_TYPE_LIST vs enqueue_documents() 의 리터럴 --------------------
    m = re.search(r"^DOC_TYPE_LIST\s*=\s*\[([^\]]*)\]", cfg, re.M)
    check_true("config에 DOC_TYPE_LIST가 있다", bool(m), None)
    db = read("storage/database.py")
    if m and db:
        cfg_types = [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
        # `for doc_type in ("spec", "status", ...)` 형태를 찾는다
        m2 = re.search(r"for\s+doc_type\s+in\s*\(([^)]*)\)", db)
        check_true("enqueue_documents의 doc_type 루프를 찾았다", bool(m2), None)
        if m2:
            copy_types = [x.strip().strip("'\"") for x in m2.group(1).split(",") if x.strip()]
            check("DOC_TYPE_LIST와 enqueue 루프가 같은 종류를 쓴다",
                  sorted(copy_types), sorted(cfg_types))
            check("순서까지 같다(우선순위 의미가 있을 수 있다)", copy_types, cfg_types)

    # --- (2) PRIORITY_REFRESH_TIME vs 등록 스크립트의 Time ---------------------
    m3 = re.search(r"^PRIORITY_REFRESH_TIME\s*(?::\s*str\s*)?=\s*[\"']([0-9:]+)[\"']", cfg, re.M)
    check_true("config에 PRIORITY_REFRESH_TIME이 있다", bool(m3), None)
    ps1 = read("register_scheduler_tasks.ps1")
    if m3 and ps1:
        m4 = re.search(r"PriorityRefresh[^\n]*?Time\s*=\s*'([0-9:]+)'", ps1)
        check_true("등록 스크립트에서 PriorityRefresh 시각을 찾았다", bool(m4), None)
        if m4:
            check("PRIORITY_REFRESH_TIME과 스케줄러 등록 시각이 같다",
                  m4.group(1), m3.group(1))

    # --- (4) DOC_WORKER_START_TIME vs 등록 스크립트의 DocWorker 시각 -----------
    #
    # 2026-08-18 Sprint 204 추가. `config/settings.py` 의 이 상수 주석은 이미
    # "예약 작업 등록 시각과 같아야 한다 — register_scheduler_tasks.ps1" 이라고
    # 적고 있었다. **적혀만 있고 지키는 것이 없었다.**
    #
    # 어긋나면 조용하다. 이 값은 `DOC_WORKER_END_TIME` 과 함께 **실행 창 길이**를
    # 만들고, 그 길이가 `REFRESH_MAX_ITEMS_PER_RUN` 상한의 근거다
    # (`test_refresh_trigger.py` 17번). 스케줄러를 03:00 으로 옮기고 config 를
    # 그대로 두면, 실제로는 1시간짜리 창인데 산술은 2시간으로 계산한다 —
    # 큐가 절반만 소진되고 아무도 실패를 보지 않는다.
    m5 = re.search(r"^DOC_WORKER_START_TIME\s*(?::\s*str\s*)?=\s*[\"']([0-9:]+)[\"']",
                   cfg, re.M)
    check_true("config에 DOC_WORKER_START_TIME이 있다", bool(m5), None)
    if m5 and ps1:
        m6 = re.search(r"DocWorker[^\n]*?Time\s*=\s*'([0-9:]+)'", ps1)
        check_true("등록 스크립트에서 DocWorker 시각을 찾았다", bool(m6), None)
        if m6:
            check("DOC_WORKER_START_TIME과 스케줄러 등록 시각이 같다",
                  m6.group(1), m5.group(1))

    # --- (5) 실행 순서: 우선순위 재계산이 문서 수집보다 **먼저** ----------------
    #
    # 등록 스크립트 자신이 근거를 적어 두었다 —
    # "순서가 중요하다: 우선순위가 먼저 갱신돼야 임박 물건이 문서 수집에서 앞으로 온다."
    #
    # 두 시각을 뒤바꾸면 그날 우선순위 갱신은 **이미 끝난 수집에** 적용된다.
    # 오류도 빈 결과도 아니고, 그냥 임박 물건이 뒤로 밀린다. 알아챌 신호가 없다.
    if ps1:
        mp = re.search(r"PriorityRefresh[^\n]*?Time\s*=\s*'([0-9:]+)'", ps1)
        md = re.search(r"DocWorker[^\n]*?Time\s*=\s*'([0-9:]+)'", ps1)
        check_true("두 시각을 모두 찾았다", bool(mp) and bool(md), (bool(mp), bool(md)))
        if mp and md:
            def _mins(hhmm):
                h, mm = hhmm.split(":")
                return int(h) * 60 + int(mm)
            check_true("우선순위 재계산(%s)이 문서 수집(%s)보다 먼저다"
                       % (mp.group(1), md.group(1)),
                       _mins(mp.group(1)) < _mins(md.group(1)),
                       (mp.group(1), md.group(1)))

    # --- (6) 스케줄러 실행시간 한계가 worker 자신의 창보다 짧지 않은가 -----------
    #
    # worker 는 `DOC_WORKER_END_TIME` 까지 돌 생각으로 큐를 잡는다. 스케줄러의
    # `ExecutionTimeLimit` 이 그보다 짧으면 **Windows 가 중간에 죽인다.**
    # worker 는 자기가 끝냈다고 기록할 기회조차 없고, 잡아 둔 큐 행은
    # `in_progress` 로 남는다(만료 회수는 되지만 그날 수집은 조용히 잘린다).
    m7 = re.search(r"^DOC_WORKER_END_TIME\s*(?::\s*str\s*)?=\s*[\"']([0-9:]+)[\"']",
                   cfg, re.M)
    if m5 and m7 and ps1:
        m8 = re.search(r"ExecutionTimeLimit\s*\(New-TimeSpan\s+-Hours\s+(\d+)\)", ps1)
        check_true("등록 스크립트에서 ExecutionTimeLimit을 찾았다", bool(m8), None)
        if m8:
            def _mins2(hhmm):
                h, mm = hhmm.split(":")
                return int(h) * 60 + int(mm)
            window = _mins2(m7.group(1)) - _mins2(m5.group(1))
            limit = int(m8.group(1)) * 60
            # ★ 창이 음수면 이 비교는 **언제나 참**이다 - 공허하게 통과한다
            #   (2026-08-20 Sprint 237). 종료가 시작보다 앞서면 `is_time_up()` 이
            #   기동 즉시 True 를 돌려주어 그날 수집이 통째로 사라지는데,
            #   여기서는 그것이 "한계 안에 들어온다"로 읽힌다.
            check_true("실행 창이 양수다(음수면 아래 비교가 공허해진다)",
                       window > 0,
                       "종료 %s 가 시작 %s 보다 앞선다 - 워커가 기동 즉시 끝난다"
                       % (m7.group(1), m5.group(1)))
            check_true("스케줄러 실행시간 한계(%d분)가 worker 실행 창(%d분) 이상이다"
                       % (limit, window), limit >= window, (limit, window))

    # --- (7) ★ 문서 수집 창이 **사건 크롤 시작 전에** 닫히는가 -----------------
    #
    # 2026-08-20 Sprint 230 신설. 여기가 스케줄 산술에서 유일하게 비어 있던 다리다.
    #
    # 세 작업 중 **둘이 Chrome 을 띄운다.**
    #
    #     DocWorker  -> doc_worker.py     -> build_download_driver()  (다운로드 폴더 사용)
    #     DailyCrawl -> mvp_scraper.py    -> crawl_court() -> base_crawler.build_driver()
    #
    # 지금 값은 안전하다 — 문서 수집 창이 04:00 에 닫히고 사건 크롤은 06:00 에 시작한다.
    # 그런데 **그 관계를 지키는 것이 아무것도 없었다.** `DOC_WORKER_END_TIME` 을
    # 큐를 더 소진하려고 07:00 으로 늘리는 것은 지극히 자연스러운 변경인데,
    # 그 순간 두 크롤러가 **같은 법원 사이트를 동시에** 두드린다.
    #
    # 증상이 조용하다 — 둘 다 자기 락(mvp_scraper.lock / doc_worker.lock)을 갖고 있어
    # **서로를 막지 못한다.** 락은 자기 자신의 중복 실행만 막는다.
    # 세션 간섭·법원 부하·다운로드 폴더 교차는 전부 "가끔 실패"로만 나타난다.
    #
    # DailyCrawl 시각은 config 에 상수가 **없다**(다른 둘과 달리). 그래서 PS1 에서 읽는다.
    if m7 and ps1:
        mdc = re.search(r"DailyCrawl[^\n]*?Time\s*=\s*'([0-9:]+)'", ps1)
        check_true("등록 스크립트에서 DailyCrawl 시각을 찾았다", bool(mdc), None)
        if mdc:
            def _m(hhmm):
                h, mm = hhmm.split(":")
                return int(h) * 60 + int(mm)
            check_true("★ 문서 수집 창(~%s)이 사건 크롤 시작(%s) 전에 닫힌다"
                       % (m7.group(1), mdc.group(1)),
                       _m(m7.group(1)) <= _m(mdc.group(1)),
                       "겹치면 Chrome 두 개가 같은 법원을 동시에 두드린다: %s vs %s"
                       % (m7.group(1), mdc.group(1)))

            # --- (7-b) ★ **여유**가 있는가 - 같기만 해서는 부족하다 -------------
            #
            # 2026-08-20 Sprint 237 추가. 위 검사는 `<=` 라 **종료 시각 == 크롤 시작**
            # 을 통과시킨다. 그런데 워커는 그 시각에 딱 멈추지 않는다:
            # `is_time_up()` 은 루프 **맨 위**에서만 검사되므로, 이미 집어서 처리 중이던
            # 행 하나는 종료 시각을 **지나서도** 끝까지 처리된다.
            #
            # 실측(logs/doc_run.log 907구간): 행 1개 처리 최대 **42.2초**.
            # 코드가 허용하는 이론 최대는 그보다 크다 - wait_for_detail 20초
            # (40회 x 0.5초) + OVERLAY_TIMEOUT 15초 + NEW_WINDOW_TIMEOUT 15초.
            #
            # 그래서 END == 06:00 으로 두면 06:00 에 시작하는 사건 크롤과 **실제로**
            # 겹친다. 둘은 서로의 락을 보지 않으므로(각자 자기 중복만 막는다) 아무도
            # 말리지 않고, 증상은 "가끔 실패"로만 나타난다.
            #
            # 여유 5분은 위 이론 최대(약 50초)의 여섯 배다. 넉넉하되, 창을 늘릴 여지를
            # 불필요하게 깎지 않는 값으로 잡았다.
            OVERRUN_MARGIN_MIN = 5
            gap = _m(mdc.group(1)) - _m(m7.group(1))
            check_true("★ 종료(%s)와 크롤 시작(%s) 사이에 %d분 이상 여유가 있다"
                       % (m7.group(1), mdc.group(1), OVERRUN_MARGIN_MIN),
                       gap >= OVERRUN_MARGIN_MIN,
                       "여유 %d분 - 마지막 행이 종료 시각을 넘겨 처리되면 크롤과 겹친다"
                       " (실측 행 1개 최대 42.2초)" % gap)

    # --- (8) ★ 진입점 목록을 손으로 적은 곳이 PS1 과 어긋나지 않는가 -----------
    #
    # `test_crawl_exit_code.py` 는 배치 3종의 이름을 **하드코딩**해 두고 errorlevel
    # 검사를 확인한다. PS1 에 네 번째 작업이 생기면 그 배치는 **아무도 검사하지 않는다** —
    # 실패 은폐 검사가 새 진입점만 비껴간다.
    #
    # 이 저장소가 이미 같은 함정을 겪었다(하드코딩한 목록만 믿기).
    # 그래서 두 목록이 같은지 여기서 대조한다. 어느 쪽이 늘어도 걸린다.
    if ps1:
        ps1_bats = set(re.findall(r"Bat\s*=\s*'([^']+)'", ps1))
        check_true("PS1 에서 배치 목록을 실제로 읽었다(검사가 공허하지 않다)",
                   len(ps1_bats) >= 3, sorted(ps1_bats))

        exitcode_src = read("test_crawl_exit_code.py")
        check_true("test_crawl_exit_code.py 를 읽었다", bool(exitcode_src), None)
        if exitcode_src:
            hardcoded = set(re.findall(r'"(run_[a-z_]+\.bat)"', exitcode_src))
            check("★ 하드코딩된 배치 목록이 PS1 의 작업 목록과 같다",
                  sorted(hardcoded), sorted(ps1_bats))

        # PS1 이 가리키는 배치가 실제로 존재하는가 (PS1 -> .bat 연결)
        missing_bat = sorted(b for b in ps1_bats
                             if not os.path.exists(os.path.join(root, b)))
        check("★ PS1 이 가리키는 배치가 전부 존재한다", missing_bat, [])

        # 그 배치가 부르는 파이썬 스크립트가 실제로 존재하는가 (.bat -> .py 연결)
        missing_py = []
        for b in sorted(ps1_bats):
            bp = os.path.join(root, b)
            if not os.path.exists(bp):
                continue
            body = open(bp, encoding="utf-8-sig", errors="replace").read()
            for script in re.findall(r'"%PY%"\s+([A-Za-z0-9_]+\.py)', body):
                if not os.path.exists(os.path.join(root, script)):
                    missing_py.append("%s -> %s" % (b, script))
        check("★ 배치가 부르는 파이썬 스크립트가 전부 존재한다", missing_py, [])

    # --- (9) 대조군 — 이 검사가 공허하지 않다 ---------------------------------
    check_true("대조군: 두 사본 파일을 실제로 읽었다",
               bool(db) and bool(ps1), (bool(db), bool(ps1)))


def test_no_escape_corrupted_text():
    """추적 파일에 **이스케이프가 해석돼 끊긴 문장**이 남아 있지 않은가 (2026-08-18 Sprint 190).

    ## 왜 이 검사가 생겼나

    셸 heredoc 은 본문의 백슬래시 이스케이프를 해석한다. 그래서 문서를 편집하며
    `` `.\\register_scheduler_tasks.ps1` `` 를 넣으면 `\\r` 이 **캐리지 리턴**이 되어
    문장이 두 줄로 쪼개진다. 실제로 `docs/BETA_RELEASE_CHECKLIST.md` 43행이 그렇게
    깨져 있었다:

        조치는 `.<CR><LF>egister_scheduler_tasks.ps1 -Apply` 한 줄이며 ...

    사람이 읽으면 바로 보이지만 **아무 검사도 이것을 보지 않는다** — 마크다운이라
    빌드도 린트도 통과하고, 내용이 아니라 표기라 문서 드리프트 감사에도 안 걸린다.
    그런데 이 문서는 **운영자가 그대로 복사해 실행하는 명령**을 담고 있다.

    같은 사고를 이 저장소는 최소 두 세션에서 겪었다(Sprint 189 작업 중에도 두 번).
    인스턴스만 고치면 반드시 다음이 남는다.

    ## 무엇을 보는가

    두 가지 표지를 본다. 어느 쪽도 정상 문서에서는 나타나지 않는다.

        (1) 줄 끝이 백틱+점 또는 홑 백슬래시인데 다음 줄이 소문자로 시작
        (2) 줄이 알려진 파일명의 **첫 글자가 잘린 조각**으로 시작
            (`\\r`->CR 이면 register 가 egister 로 남는 식)
    """
    print("\n--- 이스케이프 해석으로 끊긴 문장 (Sprint 190) ---")
    import re
    import subprocess

    root = os.path.dirname(os.path.abspath(__file__))
    EXT = {"md", "py", "ps1", "bat", "ts", "tsx", "mjs", "json", "txt", "sql", "css"}
    files = [f for f in subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split("\n")
        if f and f.rsplit(".", 1)[-1] in EXT]

    tail_re = re.compile("(`" + re.escape(".") + "|" + re.escape(chr(92)) + ")$")
    head_re = re.compile("^[a-z]")
    FRAGMENTS = ("egister_", "un_daily", "un_doc_worker", "un_priority",
                 "ode_modules", "equirements", "eset_", "efresh_")

    suspects = []
    for f in files:
        path = os.path.join(root, f)
        try:
            with open(path, encoding="utf-8-sig") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.replace("\r\n", "\n").split("\n")
        for i in range(len(lines) - 1):
            if tail_re.search(lines[i]) and head_re.match(lines[i + 1]):
                suspects.append("%s:%d" % (f, i + 1))
        for i, ln in enumerate(lines):
            if ln.startswith(FRAGMENTS):
                suspects.append("%s:%d" % (f, i + 1))

    print("    추적 텍스트 파일 %d개 검사" % len(files))
    check_true("검사 대상 파일을 실제로 찾았다", len(files) >= 100, len(files))
    check("이스케이프로 끊긴 문장 없음", sorted(set(suspects)), [])


# ---------------------------------------------------------------------------
# 27. CRLF 로 커밋된 파일을 LF 로 다시 쓰지 않는가 (2026-08-18 Sprint 202 신설)
#
# 이 세션에서 같은 사고가 두 번 났다. 파일을 통째로 읽어 고친 뒤 다시 쓰면서 줄끝이
# 바뀌어, **몇 줄 고친 변경이 전 파일 재작성으로 나타났다.**
#
#     docs/CHANGELOG.md    +3854 / -3560   (실제로 늘어난 내용은 294줄)
#     config/settings.py   +136  / -121    (실제로 늘어난 내용은 15줄)
#
# 리뷰가 불가능해지는 것이 피해다. 3,681줄의 가짜 변경 속에 진짜 15줄이 묻힌다.
#
# ★ 왜 "모든 파일의 줄끝"이 아니라 **CRLF blob 만** 보는가 (한 번 틀리고 고쳤다)
#
#   이 저장소는 `core.autocrlf=true` 다. 그래서 작업본의 CRLF 는 비교 전에 LF 로
#   정규화된다 - 즉 **LF 로 커밋된 파일은 작업본이 CRLF 든 LF 든 diff 에 나타나지
#   않는다.** 그것까지 규약 위반으로 잡으면 정상 체크아웃 97개가 걸린다(실제로 걸렸다).
#
#   그런데 git 은 **index 의 blob 에 이미 CR 이 있으면 그 경로의 정규화를 끈다**
#   (이미 CRLF 로 커밋된 파일을 뒤늦게 뒤집지 않으려는 안전장치다).
#   그래서 이 부류만은 작업본이 **글자 그대로 CRLF 를 유지해야** 한다.
#   LF 로 다시 쓰는 순간 모든 줄이 달라진다.
#
#   이 저장소에는 그런 파일이 많다(CEO/*, config/settings.py, docs/CHANGELOG.md,
#   doc_worker.py, migrate_execute.py, mvp_scraper.py ...). Windows 에서
#   autocrlf 없이 커밋되던 시절의 흔적이다.
#
# 한계를 밝혀 둔다: 이미 혼재된 blob 에서 **일부만** LF 로 바뀌는 것은 못 잡는다
# (CR 이 남아 있으면 통과한다). 잡는 것은 "규약이 통째로 뒤집힌 경우"다.
# ---------------------------------------------------------------------------
def test_crlf_blobs_are_not_rewritten_as_lf():
    print()
    print("--- 27. CRLF 로 커밋된 파일을 LF 로 다시 쓰지 않는가 (Sprint 202) ---")
    import subprocess

    root = os.path.dirname(os.path.abspath(__file__))
    LF = bytes([10])
    CR = bytes([13])
    CRLF = bytes([13, 10])
    NLCH = chr(10)

    def git(*args, **kw):
        return subprocess.run(["git"] + list(args), cwd=root, capture_output=True, **kw)

    if git("rev-parse", "--git-dir").returncode != 0:
        print("[SKIP] git 저장소가 아니다(배포본) - 줄끝 대조 생략")
        return

    tracked = [q for q in git("ls-files").stdout.decode("utf-8", "replace").split(NLCH)
               if q.strip()]

    # blob 을 한 번의 배치로 읽는다 (파일당 프로세스를 띄우면 수백 개에 수십 초가 든다)
    payload = "".join("HEAD:" + rel + NLCH for rel in tracked).encode("utf-8")
    out = git("cat-file", "--batch", input=payload).stdout

    bad = []
    crlf_blobs = 0
    parsed = 0
    pos = 0
    for rel in tracked:
        nl = out.find(LF, pos)
        if nl < 0:
            break
        header = out[pos:nl].decode("utf-8", "replace")
        pos = nl + 1
        if header.endswith("missing"):
            continue
        parsed += 1
        size = int(header.split()[2])
        blob = out[pos:pos + size]
        pos += size + 1

        blob_cr = blob.count(CR)
        if blob_cr == 0:
            continue          # autocrlf 가 정규화한다 - 작업본 줄끝은 자유다
        if blob.count(bytes([0])):
            continue          # 바이너리
        crlf_blobs += 1

        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(path, "rb") as fh:
                cur = fh.read()
        except OSError:
            continue          # 체크아웃되지 않은 파일

        cur_cr = cur.count(CR)
        if cur_cr == 0:
            bad.append("%s: HEAD 는 CRLF(%d줄)인데 작업본이 LF 로 통째로 바뀌었다"
                       % (rel, blob.count(CRLF)))

    check("CRLF 로 커밋된 파일을 LF 로 다시 쓴 것 없음", bad, [])

    # ★ 이 가드가 **아무것도 안 보는 상태로 통과**하는 것을 막는다.
    #   배치 파싱이나 경로 인코딩이 깨지면 조용히 0개를 대조하고 초록이 된다.
    check_true("CRLF blob 을 실제로 찾아냈다 (%d개 / blob %d개 파싱)"
               % (crlf_blobs, parsed), crlf_blobs >= 50, crlf_blobs)


# ---------------------------------------------------------------------------
# 28. 낡은 "도달 불가" 주장이 정정 없이 살아 있는가 (2026-08-18 Sprint 211 신설)
#
# 이 저장소는 낡은 단정 때문에 반복해서 헛돌았다.
#
#     CLAUDE.md   "No requirements.txt exists"        -> 이미 있었다
#     Sprint 187  "DOJOONPASS_DAILY 정상 동작 중"      -> 세 축 실측이 전부 반대였다
#     Sprint 145  "document_version_log 도달 불가"     -> Sprint 189 가 경로를 열었다
#
# 마지막 것이 특히 위험하다. 그 문장은 **"재수집 정책을 정할 수 없다"는 결론의 근거**로
# 여러 문서에 인용돼 있어서, 낡은 채로 두면 이미 가능해진 일을 계속 불가능하다고
# 판단하게 만든다.
#
# 코드 사실은 이미 다른 곳이 지킨다(`test_refresh_trigger.py` 18 이 재수집 배선을
# 고정한다). 여기서 지키는 것은 **문서/주석의 주장**이다.
#
# ★ 이 저장소의 관례는 낡은 문장을 지우는 대신 **그대로 인용하고 정정을 붙이는** 것이다.
#   그래서 단순 문자열 검색은 *고쳐 놓은 문서*를 위반으로 잡는다
#   (`test_bootstrap.py` 의 requirements.txt 검사가 같은 이유로 같은 방식을 쓴다).
#   주변에 정정 표시가 있으면 살아 있는 주장이 아니라 인용으로 본다.
# ---------------------------------------------------------------------------
def test_no_live_unreachable_claim_about_version_log():
    print()
    print("--- 28. 낡은 '도달 불가' 주장이 정정 없이 남아 있는가 (Sprint 211) ---")
    import re
    import subprocess

    root = os.path.dirname(os.path.abspath(__file__))

    def git(*args):
        return subprocess.run(["git"] + list(args), cwd=root, capture_output=True)

    if git("rev-parse", "--git-dir").returncode != 0:
        print("[SKIP] git 저장소가 아니다(배포본)")
        return

    NL = chr(10)
    files = []
    for args in (("ls-files",), ("ls-files", "--others", "--exclude-standard")):
        out = git(*args).stdout.decode("utf-8", "replace")
        files += [f.strip() for f in out.split(NL)
                  if f.strip().endswith((".py", ".md"))]

    # "document_version_log ... 도달 불가" 를 한 문장 안에서 찾는다.
    CLAIM = re.compile(r"document_version_log[^" + NL + r"]{0,80}도달\s*불가"
                       r"|도달\s*불가[^" + NL + r"]{0,80}document_version_log")
    # ★ 인정 조건을 좁게 잡는다. 처음에는 "정정" / "Sprint 189" 같은 흔한 단어를
    #   넣었다가 **가드가 공허해졌다** — 이 저장소는 "정정"을 워낙 자주 쓰기 때문에
    #   정정 마커를 통째로 지워도 주변 900자 안에서 그 단어가 걸렸다(변이 실측:
    #   마커 제거 -> FAIL 0건). 의도적으로 붙인 마커만 인정한다.
    CORRECTION = ("[정정", "[재정정", "더 이상 사실이 아니다")
    WINDOW = 600

    live, scanned = [], 0
    for rel in files:
        # 이 검사 자신은 제외한다 — 위 설명 주석이 바로 그 문장을 인용하고 있어
        # 스캐너가 자기 자신을 위반으로 잡는다(`test_bootstrap.py` 가 같은 부류를
        # 겪고 같은 판단을 했다). 제외 대상을 목록으로 늘리지 않는다: **자기 파일 하나뿐**이다.
        if os.path.basename(rel) == os.path.basename(__file__):
            continue
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        scanned += 1
        for m in CLAIM.finditer(text):
            line_start = text.rfind(NL, 0, m.start()) + 1
            line_end = text.find(NL, m.end())
            line = text[line_start:line_end if line_end >= 0 else len(text)]
            # 취소선(`~~...~~`)으로 그어 둔 것은 살아 있는 주장이 아니라 **이력**이다.
            # 이 저장소의 roadmap 이 완료 항목을 그렇게 표시한다.
            if "~~" in line:
                continue
            around = text[max(0, m.start() - WINDOW):m.end() + WINDOW]
            if not any(k in around for k in CORRECTION):
                live.append("%s:%d" % (rel, text[:m.start()].count(NL) + 1))

    check("정정 없이 살아 있는 '도달 불가' 주장 없음", sorted(live), [])

    # ★ 하한 - 파일 열거가 깨지면 조용히 0건을 훑고 통과한다.
    check_true("훑은 파일이 실제로 있다 (%d개)" % scanned, scanned >= 100, scanned)

    # ★ 대조군 - 이 주장이 문서에 **실제로 존재**해야 검사가 의미를 갖는다.
    #   전부 지워 버리면 위 검사는 영원히 통과하면서 아무것도 지키지 않는다.
    total = 0
    for rel in files:
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                total += len(CLAIM.findall(fh.read()))
        except OSError:
            continue
    check_true("대조군: 정정이 붙은 원문이 남아 있다 (%d곳)" % total, total >= 2, total)




def test_no_cwd_relative_paths_in_product_code():
    """추적되는 제품 코드가 **cwd 기준 상대경로**로 파일을 열지 않는가 (2026-08-21 Sprint 246).

    ## 왜 이 검사가 생겼나 - 같은 결함이 한 세션에 4건 나왔다

    상대경로는 **현재 작업 디렉터리** 기준으로 풀린다. 저장소 루트에서 띄우면 멀쩡하니
    개발 중에는 절대 드러나지 않고, 배포 방식이 바뀌는 순간 터진다. 실측한 4건:

        Sprint 245  api/auth.py   load_dotenv()          -> 다른 cwd 에서 인증 API 전부 500
        Sprint 246  storage/database.py DB_PATH          -> 0바이트 auction.db 를 만들고
                                                            "데이터 없음"처럼 보인다
        Sprint 246  doc_worker.py LOCK_PATH              -> ★ 중복 실행 방지가 조용히 무력화
        Sprint 246  운영 도구 8개 DB_PATH                 -> 찌꺼기 DB + 원인을 가리는 오류

    셋째가 가장 나쁘다 - 두 워커가 같은 큐/다운로드 폴더를 동시에 만지는데
    **양쪽 로그 모두 "락 획득 성공"** 이라 흔적이 없다.

    `.bat` 3개는 `cd /d %~dp0` 로 보호되지만, 문서가 안내하는 수동 실행
    (`uvicorn api_server:app --reload`)과 서비스 등록은 그렇지 않다.

    ## 무엇을 보는가

    문자열 grep 이 아니라 **AST** 로 본다. 두 가지를 잡는다:

      (A) 모듈 최상위 상수 할당    `DB_PATH = "auction.db"`
      (B) 경로 인자를 받는 호출     `open("logs/x.jsonl")`, `sqlite3.connect("a.db")`

    (A) 가 없으면 이 검사는 자기가 찾으려던 결함에 눈이 먼다 - 2026-08-21 에 실제로
    그랬다. (B) 만 있던 초기 버전은 고치기 전 `storage/database.py` 를 "0건"으로
    통과시켰다. 도구가 이상하면 제품보다 도구를 먼저 의심하라는 원칙 그대로,
    **알려진 결함 상태를 잡는지 먼저 확인**하고 확장했다. 이 검사도 그 확인을 내장한다
    (아래 "자기 검증").
    """
    print("\n--- cwd 기준 상대경로를 쓰는 제품 코드가 없는가 (Sprint 246) ---")
    import ast
    import io as _io

    root = os.path.dirname(os.path.abspath(__file__))
    try:
        out = subprocess.run(["git", "ls-files", "*.py"], cwd=root,
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print("[SKIP] git을 실행할 수 없다 (%s)" % type(exc).__name__)
        return
    if out.returncode != 0:
        print("[SKIP] git 저장소가 아니다")
        return

    # 테스트/감사 도구는 스스로 임시 디렉터리를 만들어 쓰므로 대상이 아니다.
    SKIP_PREFIX = ("test_", "audit_", "step", "check_", "patch_", "debug_")
    files = [f.replace("\\", "/") for f in out.stdout.split()
             if f.endswith(".py")
             and not os.path.basename(f).startswith(SKIP_PREFIX)]

    PATH_CALLS = {"open", "makedirs", "mkdir", "connect", "remove", "listdir",
                  "isfile", "isdir", "exists", "glob", "rmtree", "FileHandler"}

    def relative_literal(node, path_context=False):
        """상대경로 **문자열 리터럴**이면 그 값을 준다.

        `path_context=True` 는 "이 인자는 경로가 확실하다"는 뜻이다
        (`open(...)` / `os.path.join(...)` 의 첫 인자 등). 그때는 확장자도
        구분자도 없는 **맨 디렉터리 이름**(`"logs"`)까지 잡는다 -
        `LOCK_PATH = os.path.join("logs", "doc_worker.lock")` 이 정확히 그
        모양이었고, 확장 전 판본은 이걸 놓쳤다(자기 검증이 잡아냈다).

        할당 문맥에서는 그렇게 넓히지 않는다 - 아무 짧은 문자열이나
        경로로 오해하게 된다.
        """
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            return None
        v = node.value
        if not v or v in (".", "..", "-") or "\n" in v or " " in v:
            return None                      # 여러 줄/공백 = SQL 등. 경로가 아니다.
        if os.path.isabs(v) or v.startswith(("~", "http://", "https://", ":memory:", "/")):
            # ★ 맨 앞 "/" 는 `os.path.isabs()` 만으로는 못 잡는다 - `ntpath.isabs()`는
            #   드라이브 문자가 없으면 "/api/..." 를 **상대경로로 오판**한다(Windows 전용
            #   실측: `os.path.isabs('/api/v1/x')` == False). 그런데 이 저장소에서 맨
            #   앞이 "/"인 최상위 문자열 리터럴은 지금까지 전부 URL 라우트 템플릿이었다
            #   (예: `api/v1/thumbnails.py`의 `IMAGE_URL_TEMPLATE`) - cwd 에 좌우되는
            #   파일시스템 경로가 아니다. POSIX 에서는 애초에 절대경로라 `isabs()`가 잡고,
            #   Windows 에서는 이 줄이 대신 잡는다.
            return None
        if "/" in v or "\\" in v:
            return v
        base = os.path.basename(v)
        if "." in base and len(v) < 60:
            return v
        return v if (path_context and len(v) < 60) else None

    def scan(src):
        """(줄번호, 종류, 값) 목록. 파싱 실패하면 None."""
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return None
        hits = []
        for node in tree.body:                       # (A) 최상위 상수 할당
            if isinstance(node, ast.Assign):
                v = relative_literal(node.value)
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if v and names:
                    hits.append((node.lineno, "할당:" + names[0], v))
        for node in ast.walk(tree):                  # (C) 함수 **기본 인자값**
            # ★ 2026-08-27 (BUGS #263) - 이 갈래가 없어서 통째로 놓친 것이 있다:
            #
            #       class CheckpointManager:
            #           def __init__(self, path: str = "logs/checkpoint.json"):
            #
            #   (A) 최상위 상수 할당도 아니고 (B) 경로 호출의 인자도 아니라 둘 다
            #   비껴갔다. 그런데 **결과는 같다** - 다른 cwd 에서 띄우면 그 폴더에
            #   체크포인트가 생기고, 저장소의 진짜 체크포인트를 못 찾아
            #   **재개가 조용히 무력화된다**(어제 다 한 법원을 오늘 처음부터 다시 돈다).
            #
            #   기본 인자값은 그 자체가 "아무도 안 주면 이 경로를 쓴다"는 선언이라
            #   (A) 의 모듈 상수와 성격이 완전히 같다.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            _a = node.args
            for _d in list(_a.defaults) + [x for x in _a.kw_defaults if x is not None]:
                v = relative_literal(_d)
                if v:
                    hits.append((getattr(_d, "lineno", node.lineno),
                                 "기본인자:" + node.name, v))
        for node in ast.walk(tree):                  # (B) 경로 인자를 받는 호출
            if not isinstance(node, ast.Call) or not node.args:
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (
                f.attr if isinstance(f, ast.Attribute) else None)
            if name in PATH_CALLS or name == "join":
                # 맨 디렉터리 이름(`"logs"`)까지 잡는 것은 **디렉터리를 확실히
                # 받는 호출**로 제한한다. `remove`/`exists` 같은 이름은 리스트
                # 메서드와 구분되지 않아, 넓히면 `cols.remove("has_status_pdf")`
                # 같은 것을 경로로 오해한다(2026-08-21 실제 오탐).
                v = relative_literal(
                    node.args[0],
                    path_context=(name in ("makedirs", "mkdir", "join")))
                if v:
                    hits.append((node.lineno, name, v))

        # (D) **경로임을 이름으로 밝힌 키워드 인자** (2026-08-27, BUGS #263)
        #
        #   `ValidationEngine(log_path="logs/revalidation.jsonl")` 를 (B) 가 놓쳤다 —
        #   `ValidationEngine` 은 `PATH_CALLS` 에 없는 이름이기 때문이다. 그런데 인자
        #   이름이 `log_path` 라고 **스스로 경로라고 말하고 있다.** 호출 대상이 무엇이든
        #   그 자리에 상대경로 리터럴이 들어가면 cwd 를 따라간다.
        #
        #   이름을 보는 것이라 오탐이 적다: 값이 **문자열 리터럴일 때만** 잡는다.
        #   변수/상수를 넘기는 정상 호출(`log_path=QA_LOG_PATH`)은 걸리지 않는다.
        #   ★ `dest` 는 **일부러 뺐다.** argparse 의 `add_argument(..., dest="pattern")`
        #     은 경로가 아니라 **저장할 속성 이름**이다(`run_python_tests.py:281` 을
        #     실제로 오탐했다). 이름이 경로를 확실히 가리키는 것만 남긴다 —
        #     목록을 넓히려다 오탐을 늘리면 이 검사 전체가 무시당한다.
        PATH_KWARGS = {"path", "log_path", "db_path", "file_path", "dest_path",
                       "filename", "out_path", "lock_path",
                       "checkpoint_path", "storage_path"}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg in PATH_KWARGS:
                    v = relative_literal(kw.value, path_context=True)
                    if v:
                        hits.append((node.lineno, "인자:" + kw.arg, v))
        return hits

    # --- 자기 검증: 알려진 결함 모양을 실제로 잡는가 -------------------------
    #     이게 없으면 "0건 통과"가 **결함이 없다**는 뜻인지 **검사가 눈멀었다**는
    #     뜻인지 구분할 수 없다.
    KNOWN_BAD = (
        'import os\n'
        'DB_PATH = "auction.db"\n'
        'LOCK_PATH = os.path.join("logs", "doc_worker.lock")\n'
        'with open("logs/errors.jsonl", "a") as f:\n'
        '    pass\n'
        # (C) 기본 인자값 - BUGS #263 이 실제로 이 모양이었다.
        'def make(path="logs/checkpoint.json"):\n'
        '    return path\n'
        # (D) 경로임을 이름으로 밝힌 키워드 인자 - 역시 #263 의 실제 모양이다.
        'e = Engine(log_path="logs/revalidation.jsonl")\n'
    )
    KNOWN_GOOD = (
        'import os\n'
        '_HERE = os.path.dirname(os.path.abspath(__file__))\n'
        'DB_PATH = os.path.join(_HERE, "auction.db")\n'
        'LOCK_PATH = os.path.join(_HERE, "logs", "doc_worker.lock")\n'
        'SQL = """\nCREATE TABLE t (a TEXT);\n"""\n'
        # URL 라우트 템플릿 - 맨 앞이 "/"라 파일시스템 경로처럼 보이지만 cwd 와 무관하다
        # (2026-08-21 실측: api/v1/thumbnails.py의 IMAGE_URL_TEMPLATE 을 오탐했었다).
        'IMAGE_URL_TEMPLATE = "/api/v1/item/%d/images/%d"\n'
        # 고쳐진 기본 인자값 모양 - 오탐하면 안 된다.
        'def make(path=None):\n'
        '    return path or os.path.join(_HERE, "logs", "cp.json")\n'
        # 경로가 아닌 짧은 기본값(상태 어휘 등)도 오탐하면 안 된다.
        'def role(kind="pending"):\n'
        '    return kind\n'
        # 경로 키워드에 **변수**를 넘기는 정상 호출 - 오탐하면 안 된다.
        'e = Engine(log_path=QA_LOG_PATH)\n'
        'f = Engine(log_path=os.path.join(_HERE, "logs", "v.jsonl"))\n'
    )
    bad_hits = scan(KNOWN_BAD)
    check_true("자기 검증: 알려진 결함 5종을 전부 잡는다",
               bad_hits is not None and len(bad_hits) == 5,
               "-> %r. 못 잡으면 아래 '0건'은 아무 의미가 없다" % (bad_hits,))
    check_true("자기 검증: 그중 **기본 인자값**도 잡는다 (BUGS #263 의 모양)",
               bad_hits is not None
               and any(k.startswith("기본인자:") for _, k, _ in bad_hits),
               "-> %r" % (bad_hits,))
    check_true("자기 검증: **경로 키워드 인자**도 잡는다 (BUGS #263 의 모양)",
               bad_hits is not None
               and any(k.startswith("인자:") for _, k, _ in bad_hits),
               "-> %r" % (bad_hits,))
    good_hits = scan(KNOWN_GOOD)
    check_true("자기 검증: 고쳐진 모양과 SQL 문자열을 오탐하지 않는다",
               good_hits == [], "-> %r" % (good_hits,))

    # --- 본 검사 ------------------------------------------------------------
    findings = []
    scanned = 0
    for rel in files:
        p = os.path.join(root, rel)
        try:
            src = _io.open(p, encoding="utf-8-sig").read()
        except OSError:
            continue
        hits = scan(src)
        if hits is None:
            continue
        scanned += 1
        for ln, kind, val in hits:
            findings.append("%s:%d  %s -> %r" % (rel, ln, kind, val))

    check_true("검사가 공허하지 않다(추적 제품 .py 를 실제로 훑었다)", scanned >= 40,
               "-> %d개" % scanned)
    print("    훑은 추적 제품 .py: %d개" % scanned)
    if findings:
        for f in findings:
            print("      %s" % f)
    check_true("★ cwd 기준 상대경로를 쓰는 제품 코드가 없다",
               not findings,
               "-> %d건. 다른 폴더에서 실행하면 엉뚱한 파일을 만들거나 연다. "
               "`os.path.dirname(os.path.abspath(__file__))` 기준으로 바꿔라" % len(findings))



def test_claude_md_scheduler_claims_match_register_script():
    """`docs/CLAUDE.md` 의 스케줄러 작업 이름이 **등록 스크립트와 일치하는가**
    (2026-08-21 Sprint 247 신설).

    ## 왜 생겼나 - 항상 로드되는 문서가 틀려 있었다

    `docs/CLAUDE.md` 는 세션마다 컨텍스트로 들어가는 색인 문서다. 거기 적힌 것이
    틀리면 **그 오류가 이후 모든 판단에 전파된다.**

    2026-08-21 실측에서 두 군데가 틀렸다:

        제목    "Task Scheduler job `LawAuctionDailyCrawl`"
        본문    "Task Scheduler(`LawAuctionDailyCrawl`, `PDF우선순위갱신`)도 ...
                 지금은 모두 Desktop\\dojoonpass 로 통일했다"

    두 이름 다 **옛 이름**이다. `register_scheduler_tasks.ps1` 이 실제로 등록/조회하는
    이름은 `DojoonPass-DailyCrawl` / `DojoonPass-DocWorker` / `DojoonPass-PriorityRefresh`
    다. 게다가 문장이 "통일했다"로 끝나 **지금 정상 동작 중인 것처럼 읽힌다** -
    실측하면 셋 다 미등록이고, 그게 지금의 Release Blocker다.

    옛 이름으로 스케줄러를 뒤지면 아무것도 안 나오고, 그걸 "원래 그런가 보다"로
    넘기게 된다. 이름이 맞아야 "없다"가 **결함 신호**로 읽힌다.

    ## 무엇을 고정하는가

    등록 여부는 **검사하지 않는다** - 등록은 승인 영역이고, 기계마다 다르며,
    미등록이 곧 코드 결함은 아니다. 대신 **문서와 등록 스크립트의 이름이 어긋나는
    것**을 잡는다. 이건 순수한 저장소 내부 일관성이라 어느 기계에서나 판정이 같다.
    """
    print("\n--- CLAUDE.md 의 스케줄러 이름이 등록 스크립트와 맞는가 (Sprint 247) ---")
    import io as _io
    import re as _re

    root = os.path.dirname(os.path.abspath(__file__))
    ps1 = os.path.join(root, "register_scheduler_tasks.ps1")
    md = os.path.join(root, "docs", "CLAUDE.md")

    if not os.path.exists(ps1):
        check_true("등록 스크립트가 있다", False, ps1)
        return

    ps_src = _io.open(ps1, encoding="utf-8-sig", errors="replace").read()
    # PowerShell 정의: @{ Name = 'DojoonPass-XXX'; ... }
    defined = set(_re.findall(r"Name\s*=\s*'([^']+)'", ps_src))
    check_true("검사가 공허하지 않다(등록 스크립트에서 이름을 읽었다)",
               len(defined) >= 3, "-> %s" % sorted(defined))
    if len(defined) < 3:
        return

    md_src = _io.open(md, encoding="utf-8-sig", errors="replace").read()

    # (1) 등록 스크립트가 정의한 이름이 문서에 **하나라도** 나와야 한다.
    #     (세 개 전부를 요구하지는 않는다 - 문서가 대표 이름만 쓸 수도 있다.)
    mentioned = sorted(n for n in defined if n in md_src)
    check_true("★ CLAUDE.md 가 현재 작업 이름을 쓴다",
               len(mentioned) > 0,
               "-> 등록 스크립트는 %s 를 쓰는데 문서에는 하나도 없다. "
               "옛 이름으로 스케줄러를 뒤지면 '없음'을 정상으로 오해한다"
               % sorted(defined))

    # (2) 옛 이름을 **정정 없이** 쓰고 있지 않은가.
    #     역사적 기록으로 남기는 것은 괜찮다 - 다만 "옛 이름"이라고 밝혀야 한다.
    STALE = ["LawAuctionDailyCrawl", "PDF우선순위갱신"]
    for old in STALE:
        if old not in md_src:
            continue
        # 그 이름이 나오는 문단 근처에 정정 표시가 있는가
        idx = md_src.index(old)
        window = md_src[max(0, idx - 400): idx + 1200]
        corrected = ("옛 이름" in window) or ("stale" in window.lower())
        check_true("★ 옛 이름 %s 가 나오면 '옛 이름'이라고 밝힌다" % old,
                   corrected,
                   "-> 정정 없이 쓰이면 지금도 그 이름으로 등록돼 있다고 읽힌다")

    # (3) 실제 상태를 재는 도구를 안내하는가 - 문서 숫자를 믿지 말고 재라는 뜻이다
    check_true("★ 상태를 직접 재는 방법을 안내한다(audit_schedule_health.py)",
               "audit_schedule_health.py" in md_src,
               "-> 문서에 박힌 숫자는 언제든 stale 해진다. 재는 법을 알려줘야 한다")



def test_root_scripts_do_not_write_db_without_apply():
    """저장소 루트의 스크립트가 **묻지도 않고** 운영 DB 를 고치지 않는가
    (2026-08-21 Sprint 248 신설).

    ## 왜 생겼나 - 두 개가 무방비였다

    이 저장소의 데이터 수정 도구는 관례가 확실하다. `backfill_*.py` / `repair_*.py` /
    `reset_failures.py` / `unlock_retry.py` 는 **기본이 dry-run 이고 `--apply` 를 줘야
    실제로 쓴다.** 그런데 두 파일만 예외였다:

        fix_validator.py    `python fix_validator.py`   -> 곧바로 UPDATE + commit
        add_test_queue.py   `python add_test_queue.py`  -> 곧바로 큐에 INSERT

    둘 다 과거 디버깅 세션의 일회성 스크립트가 그대로 커밋된 것이다. 파일 이름만 보고
    "확인용이겠지" 하고 실행하면 운영 데이터가 바뀐다. 되돌릴 방법도 없다.

    ## 무엇을 보는가

    **저장소 루트의** 추적 `.py` 만 본다. `api/v1/*.py` 같은 패키지 모듈은 대상이 아니다 -
    거기 쓰기는 함수(라우트 핸들러) 안에 있고 서버가 부르는 것이지, 파일을 실행해서
    벌어지는 일이 아니다. 처음에 그 구분 없이 훑었다가 라우터 10개를 오탐했다.

    "모듈 최상위에서 쓰기가 일어나는가"를 AST 로 본다 - `def`/`class` 안이나
    `if __name__ == "__main__":` 안은 제외한다. 그런 자리에서 쓰기가 보이면
    소스에 `--apply` 가 있어야 한다.
    """
    print("\n--- 루트 스크립트가 확인 없이 운영 DB 를 고치지 않는가 (Sprint 248) ---")
    import ast
    import io as _io
    import re as _re

    root = os.path.dirname(os.path.abspath(__file__))
    try:
        out = subprocess.run(["git", "ls-files", "*.py"], cwd=root,
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print("[SKIP] git을 실행할 수 없다 (%s)" % type(exc).__name__)
        return
    if out.returncode != 0:
        print("[SKIP] git 저장소가 아니다")
        return

    SKIP_PREFIX = ("test_", "audit_", "step", "check_", "patch_", "debug_")
    WRITE_SQL = _re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|DROP\s+TABLE)\b",
                            _re.I)
    # 함수 이름으로 쓰는 경우(SQL 문자열이 안 보인다) - 실제로 이것 때문에 하나를 놓칠 뻔했다
    WRITE_CALLS = ("enqueue_documents", "commit")

    def module_level_writes(src):
        """모듈 최상위(함수/클래스/__main__ 블록 밖)에서 쓰기가 일어나면 True."""
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                 ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.If):
                t = ast.dump(node.test)
                if "__main__" in t or "__name__" in t:
                    continue          # `if __name__ == "__main__":` 은 실행 진입점이다
            seg = ast.get_source_segment(src, node) or ""
            if WRITE_SQL.search(seg):
                return True
            for call in WRITE_CALLS:
                if _re.search(r"\b%s\s*\(" % call, seg):
                    return True
        return False

    # --- 자기 검증: 알려진 모양을 실제로 잡는지 먼저 본다 -----------------------
    BAD = ("from storage.database import enqueue_documents\n"
           "enqueue_documents([{'case_no': 'x'}])\n")
    BAD2 = ("import sqlite3\n"
            "conn = sqlite3.connect('a.db')\n"
            "conn.execute(\"UPDATE auction SET validation_status = 'PASS'\")\n")
    GOOD = ("import sys\n"
            "APPLY = '--apply' in sys.argv\n"
            "def main():\n"
            "    conn.execute('UPDATE auction SET x = 1')\n"
            "    conn.commit()\n"
            "if __name__ == '__main__':\n"
            "    main()\n")
    check_true("자기 검증: 함수 호출로 쓰는 모양을 잡는다", module_level_writes(BAD) is True)
    check_true("자기 검증: SQL 로 쓰는 모양을 잡는다", module_level_writes(BAD2) is True)
    check_true("자기 검증: 함수/__main__ 안의 쓰기는 오탐하지 않는다",
               module_level_writes(GOOD) is False)

    # --- 본 검사 --------------------------------------------------------------
    offenders = []
    scanned = 0
    for rel in out.stdout.split():
        rel = rel.replace("\\", "/")
        if "/" in rel:
            continue                                   # 루트 스크립트만
        if os.path.basename(rel).startswith(SKIP_PREFIX):
            continue
        try:
            src = _io.open(os.path.join(root, rel), encoding="utf-8-sig").read()
        except OSError:
            continue
        scanned += 1
        w = module_level_writes(src)
        if w and "--apply" not in src:
            offenders.append(rel)

    check_true("검사가 공허하지 않다(루트 스크립트를 실제로 훑었다)", scanned >= 15,
               "-> %d개" % scanned)
    print("    훑은 루트 스크립트: %d개" % scanned)
    check_true("★ 확인(--apply) 없이 운영 DB 를 고치는 루트 스크립트가 없다",
               not offenders,
               "-> %s. 이 저장소 관례대로 기본 dry-run + --apply 로 바꿔라 "
               "(backfill_*/repair_*/reset_failures 참고)" % offenders)


def test_no_hardcoded_foreign_machine_paths():
    """★ 다른 컴퓨터의 사용자 프로필 절대경로가 코드에 하드코딩돼 있지 않은가
    (2026-08-22 Sprint 266, `audit_test_reality.py` 실제 발견).

    ## 왜

    `audit_test_reality.py`의 `REPO` 상수가 다른 컴퓨터의 사용자 프로필 경로(OneDrive
    Desktop 밑, 이 파일의 git 이력에 그 리터럴이 남아 있다)로 하드코딩돼 있었다 -
    **다른 컴퓨터의 경로**였다. 이 머신에서는 그 경로가 OneDrive가 동기화해 둔 빈 폴더로
    우연히 존재해서(`.next/`만 든 껍데기) `os.chdir()`/`os.listdir()`가 예외 없이 조용히
    성공하고, 그 도구는 **"의심 목록 없음"을 계속 출력하면서 실제로는 test_*.py를 단 한 번도
    실행하지 않고 있었다.** 예외도, 경고도 없었다 - 정상적으로 보이는 빈 출력뿐이었다.

    `test_no_cwd_relative_paths_in_product_code()`는 이 결함을 잡지 못한다 - 그 검사는
    **cwd-상대경로**(`"auction.db"` 같은 맨 이름)만 보고, **절대경로**는 `os.path.isabs()`가
    참이면 바로 안전하다고 판정한다(cwd 에 안 흔들리니까). 그런데 이번 결함은 절대경로
    자체가 **다른 사람의 컴퓨터에서만 유효**해서 생겼다 - 절대/상대의 문제가 아니라
    **이식성**의 문제다. 그래서 별도 검사로 잠근다.

    그 검사는 `audit_*`/`check_*` 같은 도구 스크립트를 의도적으로 건너뛴다("스스로 임시
    디렉터리를 만들어 쓰므로 대상이 아니다") - 그 가정이 이번에 깨졌다. 그래서 여기서는
    **건너뛰지 않는다.**
    """
    print("\n--- 다른 컴퓨터의 사용자 프로필 절대경로가 하드코딩돼 있지 않은가 (Sprint 266) ---")
    import ast
    import io as _io
    import re as _re
    root = os.path.dirname(os.path.abspath(__file__))
    try:
        out = subprocess.run(["git", "ls-files", "*.py"], cwd=root,
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print("[SKIP] git을 실행할 수 없다 (%s)" % type(exc).__name__)
        return
    if out.returncode != 0:
        print("[SKIP] git 저장소가 아니다")
        return

    # 이 저장소 안에서 실제로 봐도 되는 사용자 프로필 경로 하나 - 실행 중인 이 머신 것.
    # 다른 사람 이름이 나오면 그건 이 검사가 잡으려는 바로 그 결함이다.
    # 문자열 리터럴의 **실제 값**(파싱 후, 백슬래시 한 겹)에 매칭하므로 패턴도 한 겹이면 된다.
    FOREIGN_USER_PATH = _re.compile(r"[A-Za-z]:\\Users\\([A-Za-z0-9_.\-]+)\\")
    this_user = os.environ.get("USERNAME", "")

    def hardcoded_foreign_paths(src):
        """모듈 안 문자열 리터럴 중 다른 사용자 프로필 경로가 있으면 그 사용자명 목록."""
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return None
        found = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            for m in FOREIGN_USER_PATH.finditer(node.value):
                found.append(m.group(1))
        return found

    # --- 자기 검증 -------------------------------------------------------------
    BAD = 'REPO = r"C:\\Users\\someoneelse\\OneDrive\\Desktop\\dojoonpass"\n'
    GOOD = ('import os\n'
            'REPO = os.path.dirname(os.path.abspath(__file__))\n'
            '# C:\\Users\\someoneelse\\OneDrive\\Desktop\\dojoonpass 는 예전에 여기 있었다\n')
    check_true("자기 검증: 하드코딩된 다른 사용자 경로를 잡는다",
               hardcoded_foreign_paths(BAD) == ["someoneelse"])
    check_true("자기 검증: 주석 속 과거 경로 언급은 코드가 아니므로 오탐하지 않는다",
               hardcoded_foreign_paths(GOOD) == [])

    # 이 검사 파일 자신은 뺀다 - 바로 위 자기검증 픽스처(BAD/GOOD)가 예시로 만든
    # "다른 사용자 이름"이 든 문자열을 그대로 갖고 있어, 빼지 않으면 자기 자신을
    # 결함으로 잡는다(실제로 처음 구현에서 그랬다).
    _self = os.path.basename(__file__)
    files = [f for f in out.stdout.split() if f.endswith(".py") and os.path.basename(f) != _self]
    check_true("검사가 공허하지 않다(추적 .py 를 실제로 찾았다)", len(files) >= 100, len(files))

    offenders = []
    for rel in files:
        try:
            src = _io.open(os.path.join(root, rel.replace("/", os.sep)),
                           encoding="utf-8-sig").read()
        except OSError:
            continue
        users = hardcoded_foreign_paths(src)
        for u in users:
            if this_user and u == this_user:
                continue          # 지금 이 머신의 실제 사용자 - 정상
            offenders.append("%s (user=%s)" % (rel, u))

    check_true("★ 다른 컴퓨터의 사용자 프로필 절대경로가 하드코딩된 곳이 없다",
               not offenders,
               "-> %s. os.path.dirname(os.path.abspath(__file__)) 기준으로 바꿔라" % offenders)


# ---------------------------------------------------------------------------
# register_scheduler_tasks.ps1 의 "기존 작업 탐지"가 실제로 탐지하는가 (2026-08-24 Sprint 251)
#
# 이 블록이 존재하는 이유는 단 하나다 - 같은 .bat 을 가리키는 **다른 이름의 기존 작업**을
# 못 보고 -Apply 해서 하루 두 번 도는 중복 작업을 만드는 사고를 막는 것.
#
# 2026-08-24 실측으로 그 탐지가 한 종류를 통째로 놓치는 것을 확인했다.
# 필터가 `$_.Arguments` 만 봤기 때문이다:
#
#     등록 모양                                          Arguments만  Execute포함
#     cmd.exe  /c "...\run_daily.bat"                     탐지          탐지
#     Execute="...\run_daily.bat", Arguments 비어 있음    **놓침**      탐지
#
# 뒤쪽은 `schtasks /create /TR "C:\...\run_daily.bat"` 가 만드는 아주 흔한 모양이다.
# 놓치면 경고가 **아예 뜨지 않은 채** 중복이 등록된다 - 실패가 정상과 똑같이 생겼다.
#
# 그래서 이 테스트는 문구를 grep 하지 않고 **스크립트에 실제로 들어 있는 필터 식을 그대로
# 떼어내 PowerShell 로 돌린다.** 필터가 다시 Arguments 만 보게 퇴행하면 여기서 깨진다.
# ---------------------------------------------------------------------------
def test_scheduler_script_detects_legacy_tasks():
    print("\n--- register_scheduler_tasks.ps1 의 기존 작업 탐지 (Sprint 251) ---")
    import io as _io
    import re as _re
    import tempfile

    root = os.path.dirname(os.path.abspath(__file__))
    ps1 = os.path.join(root, "register_scheduler_tasks.ps1")
    if not os.path.exists(ps1):
        check_true("등록 스크립트가 있다", False, ps1)
        return
    src = _io.open(ps1, encoding="utf-8-sig", errors="replace").read()
    lines = src.splitlines()

    # (1) 열거로 얻은 작업의 실행 이력을 조회할 때 -TaskPath 를 함께 준다.
    #     실측(2026-08-24): 루트(\) 밖 폴더의 작업은 이름만으로 조회하면
    #     "The system cannot find the file specified" 로 실패한다. -ErrorAction
    #     SilentlyContinue 라 조용히 $null 이 되고, 사람이 볼 근거가 사라진다.
    info_calls = _re.findall(r"Get-ScheduledTaskInfo[^\r\n]*\$lc\.TaskName[^\r\n]*", src)
    check_true("검사가 공허하지 않다(열거 결과에 대한 이력 조회를 찾았다)",
               len(info_calls) >= 1, "-> Get-ScheduledTaskInfo ... $lc.TaskName 이 없다")
    missing_path = [c for c in info_calls if "-TaskPath" not in c]
    check("★ -TaskPath 없이 조회하는 곳", missing_path, [])

    # (2) 탐지 필터 식을 스크립트에서 **그대로** 떼어낸다.
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("$LegacyBatPattern"):
            start = i
            break
    check_true("탐지 패턴 상수를 찾았다($LegacyBatPattern)", start is not None,
               "-> 형식이 바뀌었으면 이 테스트를 함께 고칠 것")
    if start is None:
        return

    end = None
    depth = 0
    seen_brace = False
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if lines[i].count("{"):
            seen_brace = True
        if seen_brace and depth == 0:
            end = i
            break
    check_true("탐지 필터 식의 끝을 찾았다", end is not None, "-> 중괄호 균형이 맞지 않는다")
    if end is None:
        return

    snippet = "\n".join(lines[start:end + 1])
    check_true("★ 필터가 Execute 도 본다(Arguments 만 보면 직접 실행 등록을 놓친다)",
               "$($_.Execute)" in snippet or "$_.Execute" in snippet,
               "-> 떼어낸 식:\n%s" % snippet)

    # (3) 떼어낸 식을 실제로 실행해 본다. 정적 문구 검사만으로는
    #     "본다고 써 놓고 안 보는" 퇴행을 못 잡는다.
    exe = None
    for cand in ("powershell.exe", "powershell", "pwsh"):
        try:
            p = subprocess.run([cand, "-NoProfile", "-Command", "1"],
                               capture_output=True, timeout=60)
            if p.returncode == 0:
                exe = cand
                break
        except (OSError, subprocess.TimeoutExpired):
            continue
    if exe is None:
        print("      (PowerShell 이 없어 동작 확인은 건너뛴다 ― 위 정적 검사는 수행됐다)")
        return

    # ★ 반드시 raw 문자열로 쓴다. 보통 문자열로 적으면 `C:\repo\run_daily.bat` 의
    #   `\r` 이 **캐리지 리턴**이 되어 목 데이터에서 `run_daily.bat` 이라는 글자가
    #   사라지고, 필터는 아무것도 못 찾는다 - 그러면 이 테스트는 결함이 없는데도
    #   실패하거나(운이 나쁘면) 결함이 있는데도 통과한다. 실제로 한 번 그렇게 됐다.
    prelude = r"""$knownNames = @('DojoonPass-PriorityRefresh','DojoonPass-DocWorker','DojoonPass-DailyCrawl')
$MockTasks = @(
  [pscustomobject]@{ TaskName='LEGACY_CMDC'; TaskPath='\'; Actions=@([pscustomobject]@{Execute='cmd.exe'; Arguments='/c "C:\repo\run_daily.bat"'; WorkingDirectory='C:\repo'}) }
  [pscustomobject]@{ TaskName='LEGACY_DIRECT'; TaskPath='\'; Actions=@([pscustomobject]@{Execute='C:\repo\run_daily.bat'; Arguments=$null; WorkingDirectory='C:\repo'}) }
  [pscustomobject]@{ TaskName='UNRELATED'; TaskPath='\'; Actions=@([pscustomobject]@{Execute='notepad.exe'; Arguments=''; WorkingDirectory='C:\'}) }
  [pscustomobject]@{ TaskName='DojoonPass-DailyCrawl'; TaskPath='\'; Actions=@([pscustomobject]@{Execute='cmd.exe'; Arguments='/c "C:\repo\run_daily.bat"'; WorkingDirectory='C:\repo'}) }
)
"""
    # 목 데이터가 (위 함정 때문에) 망가지지 않았는지 먼저 확인한다.
    check_true("목 데이터가 온전하다(run_daily.bat 3회, 제어문자 없음)",
               prelude.count("run_daily.bat") == 3 and "\r" not in prelude,
               "-> raw 문자열이 아니면 \\r 이 캐리지 리턴이 된다")

    body = snippet.replace("Get-ScheduledTask -ErrorAction SilentlyContinue", "$MockTasks")
    check_true("검사가 공허하지 않다(Get-ScheduledTask 호출을 목으로 바꿨다)",
               "$MockTasks" in body, "-> 호출 형태가 바뀌었으면 이 테스트를 함께 고칠 것")
    postlude = "\n'RESULT:' + ((@($legacyCandidates) | ForEach-Object { $_.TaskName }) -join ',')\n"

    tmp = os.path.join(tempfile.gettempdir(), "dojoonpass_legacy_filter_probe.ps1")
    with open(tmp, "wb") as fh:
        fh.write(codecs.BOM_UTF8)
        fh.write((prelude + body + postlude).encode("utf-8"))
    try:
        p = subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
                           capture_output=True, timeout=120)
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    line = next((l for l in out.splitlines() if l.startswith("RESULT:")), None)
    check_true("떼어낸 필터가 실행됐다", line is not None,
               "-> stdout=%r stderr=%r" % (out[-400:], err[-400:]))
    if line is None:
        return
    detected = sorted(n for n in line[len("RESULT:"):].split(",") if n)
    # LEGACY_DIRECT 가 빠지면 = Arguments 만 보는 퇴행.
    # UNRELATED 가 들어가면 = 패턴이 비어 아무거나 매칭(공허한 통과).
    # DojoonPass-DailyCrawl 이 들어가면 = 자기가 등록할 이름까지 "기존 작업"으로 센다.
    check("★ 목 작업에서 탐지된 기존 작업", detected, ["LEGACY_CMDC", "LEGACY_DIRECT"])


# ---------------------------------------------------------------------------
# CLAUDE.md 가 **없는 파일/폴더를 있다고 서술**하지 않는가 (2026-08-24 Sprint 251 신설)
#
# `docs/CLAUDE.md` 는 세션마다 컨텍스트로 들어가는 색인 문서다. 여기 적힌 것이 틀리면
# 그 오류가 이후 모든 판단에 전파된다 - 바로 위 검사(스케줄러 이름)가 같은 이유로 생겼다.
#
# 2026-08-24 실측으로 한 건 더 나왔다:
#
#     "Note `src/login/` is a stale duplicate of the real `src/app/login/`."
#     -> `src/login/` 은 **존재하지 않는다**(src 아래는 app, components, lib, proxy.ts 넷뿐).
#        `docs/BETA_RELEASE_CHECKLIST.md` 는 2026-08-22 에 이미 "해결 확인"으로 적었는데
#        색인 문서만 갱신되지 않았다.
#
# 이 오류의 값비싼 점: 없는 폴더를 "정리 대상 죽은 코드"로 알고 있으면, 세션은 있지도
# 않은 것을 찾느라 시간을 쓰거나 **다른 폴더를 그것으로 착각한다.**
#
# ## 무엇을 검사하는가 - 좁게 잡는다
#
# 백틱 안의 토큰 중 **`/` 가 들어 있어 경로가 분명한 것**만 본다. 맨 파일명
# (`filter_engine.py` 처럼 하위 폴더에 있는 것)은 위치를 특정하지 않는 참조라 제외한다 -
# 넓히면 오탐이 실제 결함보다 많아지고, 그러면 아무도 안 본다(이 저장소가 반복해서
# 배운 것).
#
# 그리고 **없어진 것을 없어졌다고 적는 것은 정상**이다. 그래서 그 토큰 **바로 옆**에
# 제거/개명 표시가 있으면 넘어간다. 실제로 CLAUDE.md 에는 그런 정상 서술이 둘 있다:
#
#     `storage/migrate_doc_collect.py` 는 Migration 017로 대체되어 **제거됐다**
#     `src/proxy.ts` ... **renamed from** `src/middleware.ts` in Sprint 50
# ---------------------------------------------------------------------------
# 한 문장 안에서 "절"을 가르는 문자들. 제거/개명 표시는 자기가 설명하는 경로와
# **같은 절** 안에 있어야 한다 - 옆 절의 표시를 빌려 쓰면 이 검사가 눈이 먼다.
#
# ★ EM DASH(U+2014)를 `chr()`로 만든다. 이 저장소는 cp949로 못 내보내는 문자가
#   출력 리터럴에 섞이는 것을 `test_console_encoding.py`가 막는데, 그 검사는
#   `test_*.py`의 **모든** 문자열 상수를 본다(문서화 문자열 제외). 여기서 U+2014는
#   출력할 글자가 아니라 **찾을 대상 데이터**라 그 규칙의 취지 밖이지만, 검사기가
#   둘을 구별할 수는 없다. 리터럴로 적지 않으면 둘 다 만족한다.
CLAUSE_SEPARATORS = (chr(0x2014), chr(0x2015), ",", ";", ":", "(", ")", ".")

REMOVAL_MARKERS = (
    "renamed", "removed", "deleted",
    "\uc81c\uac70\ub410", "\uc81c\uac70\ud588", "\uc0ad\uc81c\ub410", "\uc0ad\uc81c\ud588",
    "\ub300\uccb4\ub418\uc5b4", "\uc5c6\uc5b4\uc9c4", "\ub354 \uc774\uc0c1 \uc5c6",
    "\uc774\ub984\ub9cc \ubcc0\uacbd", "\uc874\uc7ac\ud558\uc9c0 \uc54a",
)


def _claude_md_missing_paths(text, root):
    """`text` 안에서 **실재하지 않는데 없어졌다는 표시도 없는** 경로 토큰을 돌려준다.

    ## 표시를 토큰에 **묶는** 방법 (여기가 이 검사의 핵심이다)

    처음에는 토큰 앞뒤 120자를 훑어 제거/개명 표시를 찾았다. **그 방식은 눈이 멀었다** -
    mutation 으로 확인했다: 정상적인 개명 서술("`src/proxy.ts` ... renamed from
    `src/middleware.ts`")이 있는 **같은 줄에** 가짜 경로를 심었더니, 그 'renamed' 가
    120자 안에 들어와 가짜 경로까지 함께 면제됐다. 한 줄에 표시가 하나만 있어도 그 줄의
    모든 경로가 통과하는 셈이라, 이 검사가 있으나 마나가 된다.

    그래서 표시를 찾는 범위를 **그 토큰의 이웃**으로 좁힌다 - 바로 앞 백틱 토큰이 끝나는
    자리부터 바로 뒤 백틱 토큰이 시작하는 자리까지(줄을 넘지 않는다). 그것만으로도
    부족해서 절 구분자(`CLAUSE_SEPARATORS`)에서 한 번 더 자른다. 아래
    "같은 줄의 다른 개명 표시를 빌려 쓰지 않는다" 자기 검증이 이 두 번째 조임을 잠근다.
    """
    import os as _os
    import re as _re

    spans = [(m.group(1), m.start(), m.end()) for m in _re.finditer(r"`([^`\s]+)`", text)]
    missing = []
    for i, (tok, start, end) in enumerate(spans):
        if "/" not in tok or "*" in tok:
            continue
        if tok.startswith(("http://", "https://", "/api/")):
            continue
        if _os.path.exists(_os.path.join(root, tok.replace("/", _os.sep))):
            continue
        lo = spans[i - 1][2] if i > 0 else 0
        hi = spans[i + 1][1] if i + 1 < len(spans) else len(text)
        # 줄을 넘지 않는다 - 다른 문단의 표시를 빌려 오면 안 된다.
        lo = max(lo, text.rfind("\n", 0, start) + 1)
        nl = text.find("\n", end)
        hi = min(hi, nl if nl != -1 else len(text))
        # 앞쪽은 **마지막** 구분자 뒤부터, 뒤쪽은 **첫** 구분자 앞까지만 본다.
        before, after = text[lo:start], text[end:hi]
        cut = max([before.rfind(sep) for sep in CLAUSE_SEPARATORS] + [-1])
        if cut >= 0:
            before = before[cut + 1:]
        ends = [after.find(sep) for sep in CLAUSE_SEPARATORS]
        ends = [e for e in ends if e >= 0]
        if ends:
            after = after[:min(ends)]
        neighborhood = (before + " " + after).lower()
        if any(mk.lower() in neighborhood for mk in REMOVAL_MARKERS):
            continue          # 없어졌다고 밝히고 있다 - 정상
        missing.append(tok)
    return sorted(set(missing))


def test_claude_md_paths_exist():
    print("\n--- CLAUDE.md 가 없는 경로를 있다고 적지 않는가 (Sprint 251) ---")
    import io as _io
    import re as _re

    root = os.path.dirname(os.path.abspath(__file__))
    md = os.path.join(root, "docs", "CLAUDE.md")
    if not os.path.exists(md):
        check_true("CLAUDE.md 가 있다", False, md)
        return
    src = _io.open(md, encoding="utf-8-sig", errors="replace").read()

    n_paths = sum(1 for m in _re.finditer(r"`([^`\s]+)`", src)
                  if "/" in m.group(1) and "*" not in m.group(1))
    check_true("검사가 공허하지 않다(경로형 토큰을 찾았다)",
               n_paths >= 10, "-> %d개" % n_paths)

    missing = _claude_md_missing_paths(src, root)
    check("★ 존재하지 않는데 제거/개명 표시도 없는 경로", missing, [])
    if missing:
        print("      -> 없는 것을 있다고 적으면 이후 모든 세션이 그것을 믿는다."
              " 고치거나, 없어졌다고 밝힐 것")

    # 자기 검증 - 실제 문서와 **같은 함수**로 돌린다(로직을 복제하지 않는다).
    check("자기 검증: 없는 경로를 잡는다",
          _claude_md_missing_paths("Note `src/qa_does_not_exist/` is a duplicate.", root),
          ["src/qa_does_not_exist/"])
    check("자기 검증: '제거됐다'로 밝힌 경로는 오탐하지 않는다",
          _claude_md_missing_paths("`storage/qa_gone.py` 는 Migration 017로 대체되어 제거됐다.", root),
          [])
    check("자기 검증: 실재하는 경로는 잡지 않는다",
          _claude_md_missing_paths("라우팅은 `src/proxy.ts` 가 담당한다.", root), [])
    # ★ 이 검사가 한 번 눈이 멀었던 바로 그 모양 - 같은 줄의 정상 개명 서술이
    #   옆의 가짜 경로까지 면제해 주면 안 된다.
    check("★ 자기 검증: 같은 줄의 다른 개명 표시를 빌려 쓰지 않는다",
          _claude_md_missing_paths(
              "(`src/lib/supabaseServer.ts`, `src/qa_ghost/` gates stuff "
              "\u2015 renamed from `src/middleware.ts` in Sprint 50)", root),
          ["src/qa_ghost/"])


# ---------------------------------------------------------------------------
# 추적 대상에 **SQLite 데이터베이스 파일**이 새로 들어오지 않는가 (2026-08-24 Sprint 251)
#
# ## 위 6-2 검사와 무엇이 다른가 (이게 핵심이다 - 중복이 아니다)
#
# 6-2(`test_no_new_tracked_but_ignored_files`)는 **`.gitignore` 가 무시하겠다고 말해
# 놓고 실제로는 추적 중인 파일**을 잡는다. 지금 추적 중인 DB 백업 9개(36.9MB)는
# `.gitignore:73 *.db.backup*` 에 걸리므로 그 검사가 이미 전부 덮고 있다.
#
# **덮지 못하는 것이 있다: 어떤 무시 규칙에도 안 걸리는 이름의 데이터베이스.**
# 실측(2026-08-24)으로 확인했다 -
#
#     git check-ignore  auction.db.backup_20260728_103355  -> .gitignore:73 *.db.backup*  (6-2가 잡는다)
#     git check-ignore  qa_snapshot_2026 / db_dump_for_debug -> **무시 안 됨**            (6-2가 못 잡는다)
#
# 확장자 없는 이름, `fixtures/sample`, `snapshot_before_x` 같은 이름으로 SQLite 파일이
# 커밋되면 6-2는 아무 말도 하지 않는다. 그래서 여기서는 **이름이 아니라 내용**으로 본다:
# SQLite 매직 바이트(`SQLite format 3\0`, 16바이트). 추적 파일 401개 전수로 0.05초다.
#
# ## 왜 잡아야 하나 - 저장소 크기가 아니라 **다음번**이 문제다
#
# 지금 9개 안의 사용자 데이터는 전부 합성이다(6-2 주석의 실측: `user_id` 가 전부 `qa-*`).
# 그래서 **지금은** 유출이 아니다. 그러나 운영 DB 스냅숏을 커밋하는 습관이 남아 있으면,
# 실사용자가 생긴 뒤 뜬 스냅숏 하나가 같은 방식으로 들어온다 - 그때는
# `favorites`/`payments`/`recent_items` 에 진짜 `user_id` 가 있고, git 이력에서
# 지우는 비용은 비교가 안 되게 커진다.
#
# allowlist 는 **6-2 의 목록을 그대로 재사용한다.** 같은 9개를 여기 다시 적으면
# 한쪽만 갱신되는 날이 온다(이 저장소가 BUGS #78 에서 얻은 교훈 그대로).
# git 에서 빼는 것은 commit 이 필요해 승인 영역이므로, 여기서도 **늘어나는 것만** 막는다.
# ---------------------------------------------------------------------------
SQLITE_MAGIC = b"SQLite format 3\x00"


def test_no_new_tracked_sqlite_databases():
    print("\n--- 추적 대상에 새 SQLite DB 가 들어오지 않았는가 (Sprint 251) ---")
    root = os.path.dirname(os.path.abspath(__file__))

    try:
        ls = subprocess.run(["git", "ls-files", "-z"], cwd=root,
                            capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print("[SKIP] git 을 실행할 수 없다 (%s)" % type(exc).__name__)
        return
    if ls.returncode != 0:
        print("[SKIP] git 저장소가 아니다")
        return

    paths = [p.decode("utf-8", "replace") for p in ls.stdout.split(b"\x00") if p]
    check_true("추적 파일 목록을 얻었다 (%d개)" % len(paths), len(paths) > 50, len(paths))

    found, total_bytes = set(), 0
    for rel in paths:
        full = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(full, "rb") as fh:
                head = fh.read(len(SQLITE_MAGIC))
            if head == SQLITE_MAGIC:
                found.add(rel)
                total_bytes += os.path.getsize(full)
        except OSError:
            continue          # 작업 트리에 없는 것은 판정 대상이 아니다

    print("    추적 중인 SQLite 파일 %d개 / %.1f MB" % (len(found), total_bytes / 1048576.0))

    # ★ 목록을 복제하지 않는다 - 6-2 가 이미 들고 있는 것을 그대로 쓴다.
    check_true("검사가 공허하지 않다(6-2 의 allowlist 를 읽었다)",
               len(KNOWN_TRACKED_BUT_IGNORED) > 0, KNOWN_TRACKED_BUT_IGNORED)
    # OneDrive 충돌 사본은 제품이 아니다 — 전용 검사가 따로 센다(#253).
    new = sorted(r for r in (found - KNOWN_TRACKED_BUT_IGNORED)
                 if not is_onedrive_conflict(r))
    check("★ 새로 추적된 SQLite DB(6-2 목록 밖)", new, [])
    if new:
        print("      -> 이름이 무시 규칙에 안 걸려도 데이터베이스는 데이터베이스다."
              " 실사용자 데이터가 들어간 뒤에는 git 이력에서 지우는 비용이 훨씬 커진다")

    # 자기 검증 - 매직 바이트 판정이 실제로 동작하는가(공허하지 않은가).
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        real = os.path.join(td, "probe.sqlite")
        # ★ 반드시 닫는다. Windows 는 열린 파일을 지우지 못해
        #   TemporaryDirectory 정리가 PermissionError 로 죽는다(실측).
        probe = sqlite3.connect(real)
        try:
            probe.execute("CREATE TABLE t(a)")
            probe.commit()
        finally:
            probe.close()
        with open(real, "rb") as fh:
            is_db = fh.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC
        plain = os.path.join(td, "plain.txt")
        with open(plain, "wb") as fh:
            fh.write(b"SQLite format 2\x00 not really")
        with open(plain, "rb") as fh:
            is_not_db = fh.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC
    check_true("자기 검증: 진짜 SQLite 파일을 잡는다", is_db)
    check_true("자기 검증: 비슷한 텍스트는 잡지 않는다", not is_not_db)



def test_entrypoints_do_not_attach_file_logs_on_import():
    """진입점을 import 하는 것만으로 운영 로그 파일이 열리면 안 된다 (BUGS #192).

    ## 왜 이 검사가 있는가

    `collect_documents.py` / `mvp_scraper.py` 는 모듈 최상위에서
    `logging.basicConfig(handlers=[logging.FileHandler(...)])` 를 불렀다. basicConfig 는
    **루트 로거**를 건드리므로, 그 모듈을 import 한 순간 그 프로세스의 **모든**
    로그(crawler/* 포함)가 운영 로그 파일로 흘러간다. 이 모듈을 import 하는 것은
    제품 코드가 아니라 **테스트뿐**이라(2026-08-25 전수 확인), 결과적으로 회귀
    스위트가 돌 때마다 합성 로그가 운영 로그에 쌓였다. 실측(2026-08-25):

        logs/doc_collect.log    4,136줄 중 1,651줄(40%)이 QA 산출물('QA법원')
        logs/scraper.log       36,420줄 중 08-24~25 자 2,346줄이 QA 산출물('QA1'/'QA2')

    마지막 실제 크롤은 2026-08-12 다. 즉 로그만 읽으면 "오늘 돌았고 전 법원이
    실패했다"로 보인다 - 이 저장소가 9일간 크롤 중단을 몰랐던 그 거짓 증거와
    같은 계열이다(BUGS #186 이 DB 축에서 고친 것의 파일 판).

    ## 무엇을 검사하는가

    문자열이 아니라 **행위**를 본다 - 자식 프로세스에서 진짜로 import 해 루트
    로거에 FileHandler 가 붙는지 물어본다. 자식 프로세스로 돌리는 이유는 둘이다:
    (1) 이 검사 자신이 로그를 오염하지 않기 위해, (2) 이미 import 된 모듈이나
    먼저 설정된 루트 핸들러 때문에 basicConfig 가 no-op 이 되는 것을 피하기 위해.
    """
    import ast
    import json
    import tempfile

    print("\n--- 진입점 import 가 운영 로그를 여는가 (BUGS #192) ---")
    root = os.path.dirname(os.path.abspath(__file__))

    # .bat / 수동으로 직접 실행되는 루트 진입점 전부.
    ENTRYPOINTS = ("mvp_scraper", "collect_documents", "doc_worker", "refresh_priority")

    PROBE = (
        "import sys, os, json, logging\n"
        "sys.path.insert(0, %r)\n"
        "import %s\n"
        "print('__FH__' + json.dumps("
        "[os.path.basename(h.baseFilename) for h in logging.getLogger().handlers"
        " if isinstance(h, logging.FileHandler)]))\n"
    )

    def file_handlers_after_import(modname, sys_path):
        out = subprocess.run([sys.executable, "-c", PROBE % (sys_path, modname)],
                             cwd=root, capture_output=True, timeout=180)
        text = (out.stdout or b"").decode("utf-8", "replace")
        for line in text.splitlines():
            if line.startswith("__FH__"):
                return json.loads(line[len("__FH__"):])
        raise AssertionError("probe 가 답하지 않았다 (%s): %s / %s"
                             % (modname, text[-400:],
                                (out.stderr or b"").decode("utf-8", "replace")[-400:]))

    for mod in ENTRYPOINTS:
        handlers = file_handlers_after_import(mod, root)
        check("%s 를 import 한 뒤 루트의 FileHandler" % mod, handlers, [])

    # --- 자기 검증 1: 검사가 공허하지 않다 -------------------------------
    # 진짜로 붙이는 모듈을 놓고 같은 probe 를 돌려 **잡히는지** 확인한다.
    # 이것이 없으면 probe 가 항상 빈 목록을 돌려도 전부 초록이 된다.
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "logs"), exist_ok=True)
        bad = os.path.join(td, "qa_bad_entrypoint.py")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write(
                "import logging, os\n"
                "_HERE = os.path.dirname(os.path.abspath(__file__))\n"
                "logging.basicConfig(level=logging.INFO, handlers=["
                "logging.FileHandler(os.path.join(_HERE, 'logs', 'qa_probe.log'),"
                " encoding='utf-8'), logging.StreamHandler()])\n"
            )
        caught = file_handlers_after_import("qa_bad_entrypoint", td)
    check_true("자기 검증: import 시점에 붙이는 모듈은 잡힌다",
               caught == ["qa_probe.log"], caught)

    # --- 자기 검증 2: 운영 경로는 그대로 남아 있다 -----------------------
    # 붙이지 "않는" 것만 확인하면 **아예 파일 로그를 지워버린** 회귀를 놓친다.
    # `.bat` 이 `python <파일>` 로 부를 때는 반드시 붙어야 한다.
    for name in ("mvp_scraper.py", "collect_documents.py"):
        src = open(os.path.join(root, name), encoding="utf-8-sig").read()
        tree = ast.parse(src)
        has_fn = any(isinstance(n, ast.FunctionDef) and n.name == "attach_file_log"
                     for n in tree.body)
        check_true("%s 에 attach_file_log() 가 있다" % name, has_fn)
        main_calls = []
        for node in tree.body:
            if not isinstance(node, ast.If):
                continue
            if "__main__" not in ast.dump(node.test):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    main_calls.append(sub.func.id)
        check_true("%s 의 __main__ 이 attach_file_log() 를 부른다" % name,
                   "attach_file_log" in main_calls, main_calls)

    # --- 두 벌로 둔 구현이 **갈라지지 않는가** (2026-08-25, BUGS #204) ---
    #
    #   BUGS #192 는 `attach_file_log()` 를 두 진입점에 **일부러 인라인**했다 —
    #   새 모듈을 만들면 미추적 파일을 추적 파일이 import 하게 되어 커밋된 트리가
    #   부팅하지 못한다(BUGS #105). 그 판단은 그대로 유효하다.
    #
    #   대신 인라인이 만든 위험을 여기서 막는다: **한쪽만 고쳐지는 날**이다.
    #   BUGS #197 이 정확히 그렇게 갈라진 규칙이었다(doc_raw 작성자 둘).
    #   구조를 정규화해 비교하므로 로그 파일명·상수가 달라도 통과하고,
    #   **로직이 달라지면** 실패한다.
    import hashlib as _hashlib

    class _Norm(ast.NodeTransformer):
        """이름/상수를 지워 구조만 남긴다 - 파일명이 다른 것은 차이가 아니다."""

        def visit_Name(self, n):
            return ast.copy_location(ast.Name(id="_", ctx=n.ctx), n)

        def visit_Attribute(self, n):
            self.generic_visit(n)
            return ast.copy_location(ast.Attribute(value=n.value, attr="_", ctx=n.ctx), n)

        def visit_Constant(self, n):
            return ast.copy_location(ast.Constant(value="_"), n)

        def visit_arg(self, n):
            return ast.copy_location(ast.arg(arg="_", annotation=None), n)

    def shape_of(path, fname):
        tree = ast.parse(open(path, encoding="utf-8-sig").read())
        fn = next((n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == fname), None)
        if fn is None:
            return None
        body = [n for n in fn.body
                if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        clone = ast.parse(ast.unparse(ast.Module(body=body, type_ignores=[])))
        return _hashlib.md5(ast.dump(_Norm().visit(clone)).encode()).hexdigest()

    shapes = {name: shape_of(os.path.join(root, name), "attach_file_log")
              for name in ("mvp_scraper.py", "collect_documents.py")}
    check_true("두 진입점에서 attach_file_log() 를 찾았다",
               all(v is not None for v in shapes.values()), shapes)
    check("★ 인라인한 두 구현의 **구조가 같다**(한쪽만 고쳐지지 않았는가)",
          len(set(shapes.values())), 1)
    if len(set(shapes.values())) != 1:
        print("      -> 한쪽만 바꿨다면 다른 쪽도 같이 바꾸라. 일부러 다르게 만든 것이라면")
        print("         이 검사를 갱신하고 **왜 달라야 하는지**를 함께 적으라 (BUGS #204)")

    # 자기 검증: 이 비교가 실제로 차이를 잡는가(공허하지 않은가)
    other = shape_of(os.path.join(root, "mvp_scraper.py"), "main")
    check_true("자기 검증: 다른 함수는 다른 구조로 나온다",
               other is not None and other not in set(shapes.values()), other)



# 프런트가 보내는데 백엔드가 읽지 않는 검색 파라미터 (2026-08-25 실측, docs/BUGS.md #195).
#
# 아래 다섯은 `SearchForm.buildSearchQuery()` 가 URL 에 싣지만 `api/v1/search.py` 의
# 시그니처에 **없다.** FastAPI 는 모르는 쿼리 파라미터를 조용히 버리므로 오류도 나지
# 않는다 - 사용자 입장에서는 "필터를 걸었는데 안 걸린 결과"가 그냥 나온다.
#
# 지금은 사용자에게 도달하지 않는다. 그 값을 넣는 UI 가 "준비 중입니다"뿐이라
# (`SearchForm.tsx` 의 "면적 조건"/"특수조건" 아코디언) 손으로 URL 을 치지 않는 한
# 폼이 이 값을 만들지 않는다. 소스에도 `TODO(API 미지원)` 이 붙어 있다.
#
# **그래서 지우지 않고 목록으로 고정한다.** 이 목록이 늘어나면 새로 생긴 것이므로
# 검사가 실패한다 - "조용히 무시되는 필터"가 하나 더 생기는 것을 그때 잡는다.
# 반대로 백엔드가 이 중 하나를 실제로 구현하면 그때도 실패한다(목록에서 빼라는 신호).
# 2026-08-26: 면적 4종을 **구현하면서** 뺐다 — migration 025(building_area/land_area 컬럼),
#   normalizer.extract_areas()(주소 원문에서 추출, 실데이터 커버리지 99.3%),
#   api/v1/search.py(WHERE 절), backfill_area.py(기존 2,428행). 프런트의 '면적 조건'
#   섹션도 '준비 중입니다' 에서 실제 입력(RangeSelect)으로 바뀌었다.
#   `special_conditions` 만 남는다 — auction_item 에도 rights_summary 에도 대응 데이터가
#   없어 **뽑아낼 원천 자체가 없다**(면적과 결정적으로 다른 점이다).
KNOWN_UNSUPPORTED_SEARCH_PARAMS = {
    "special_conditions",                       # 백엔드에 대응 개념이 없다
}


def test_search_form_params_reach_the_backend():
    """프런트가 싣는 검색 파라미터가 실제로 API 시그니처에 있는가 (BUGS #195).

    ## 왜 이 검사가 필요한가

    이 저장소는 "조용히 틀리는 것"을 가장 경계한다. 모르는 쿼리 파라미터는
    FastAPI 가 **오류 없이 버린다.** 그래서 프런트가 `min_building_area=30` 을 보내도
    서버는 그냥 전체 결과를 돌려주고, 화면에는 필터가 걸린 것처럼 보인다.
    로그도 안 남고 상태 코드도 200 이다 - 검사 말고는 잡을 방법이 없다.

    ## 어떻게 비교하는가

    양쪽 다 **소스에서 직접** 읽는다. 서버를 띄우지 않으므로 회귀 스위트에서 돈다.

        백엔드   api/v1/search.py 의 `def search(...)` 시그니처 (AST)
        프런트   SearchForm.tsx 의 `FILTER_PARAM_KEYS` 배열

    `sort_by`/`sort_order`/`page`/`size` 는 검색조건이 아니라 표시 설정이라
    `FILTER_PARAM_KEYS` 에 없다(그 파일 주석이 그렇게 정의한다). 백엔드에는 있으므로
    한쪽에만 있어도 결함이 아니다 - 방향을 **프런트 -> 백엔드**로만 본다.
    """
    import ast
    import re

    print("\n--- 프런트 검색 파라미터가 백엔드에 닿는가 (BUGS #195) ---")
    root = os.path.dirname(os.path.abspath(__file__))

    api_src = open(os.path.join(root, "api", "v1", "search.py"), encoding="utf-8-sig").read()
    tree = ast.parse(api_src)
    backend = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "search":
            for a in node.args.args + node.args.kwonlyargs:
                backend.add(a.arg)
            break
    check_true("백엔드 search() 시그니처를 읽었다 (%d개)" % len(backend),
               len(backend) >= 15, sorted(backend))

    form_path = os.path.join(root, "src", "app", "search", "SearchForm.tsx")
    form_src = open(form_path, encoding="utf-8-sig").read()
    m = re.search(r"FILTER_PARAM_KEYS\s*=\s*\[(.*?)\]\s*as const", form_src, re.S)
    check_true("프런트 FILTER_PARAM_KEYS 를 찾았다", m is not None)
    if not m:
        return
    frontend = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    check_true("프런트 필터 키를 읽었다 (%d개)" % len(frontend),
               len(frontend) >= 15, sorted(frontend))

    missing = frontend - backend
    print("    프런트 %d개 / 백엔드 %d개 / 백엔드에 없는 것 %d개"
          % (len(frontend), len(backend), len(missing)))

    # ★ 알려진 것보다 **늘어나면** 실패한다. 줄어드는 것(= 백엔드가 구현했다)도 실패한다 -
    #   그때는 위 목록에서 빼야 검사가 계속 의미를 갖는다.
    check("★ 백엔드가 읽지 않는 프런트 검색 파라미터",
          sorted(missing), sorted(KNOWN_UNSUPPORTED_SEARCH_PARAMS))
    if missing - KNOWN_UNSUPPORTED_SEARCH_PARAMS:
        print("      -> 새로 생겼다. 서버는 모르는 파라미터를 **오류 없이 버린다** -"
              " 사용자에게는 '필터가 안 걸린 결과'가 그냥 나온다")
    if KNOWN_UNSUPPORTED_SEARCH_PARAMS - missing:
        print("      -> 백엔드가 구현했다. KNOWN_UNSUPPORTED_SEARCH_PARAMS 에서 빼라")

    # 아직 백엔드가 읽지 않는 것이 사용자에게 **도달하지 않는다**는 근거를 고정한다 -
    # "준비 중입니다"가 사라지면 그 순간 진짜 결함이 되기 때문이다.
    #
    # ★ 2026-08-26: "면적 조건" 은 이 목록에서 **빠졌다.** 백엔드가 구현됐으므로 그 섹션은
    #   이제 '준비 중입니다' 가 아니라 실제 입력이어야 한다 — 아래 반대 방향 검사가 그것을
    #   확인한다(다시 '준비 중' 으로 되돌리면 잡힌다).
    for title in ("특수조건",):
        idx = form_src.find('title="%s"' % title)
        check_true("'%s' 섹션이 있다" % title, idx != -1)
        if idx == -1:
            continue
        # ★ 창을 **그 섹션의 닫는 태그까지**로 자른다. 고정 길이(400자)로 잘랐더니
        #   창이 다음 섹션까지 삼켜서, 한쪽에서 "준비 중입니다" 를 지워도
        #   옆 섹션의 것이 잡혀 **검사가 통과했다**(2026-08-25 mutation 에서 발견).
        end = form_src.find("</SearchAccordionSection>", idx)
        window = form_src[idx:end if end != -1 else idx + 400]
        check_true("'%s' 은 아직 입력 UI 가 아니라 '준비 중입니다' 다" % title,
                   "준비 중입니다" in window,
                   "-> 입력 UI 가 생겼다면 위 파라미터가 실제로 전송된다."
                   " 백엔드 구현 없이는 조용히 무시된다")

    # ★ 구현된 섹션은 **반대로** 고정한다 (2026-08-26).
    #   '면적 조건' 이 다시 '준비 중입니다' 로 돌아가면, 백엔드는 파라미터를 받는데
    #   화면에서 넣을 방법이 없는 상태가 된다 — 기능이 조용히 사라진 것이다.
    _idx = form_src.find('title="면적 조건"')
    check_true("'면적 조건' 섹션이 있다", _idx != -1)
    if _idx != -1:
        _end = form_src.find("</SearchAccordionSection>", _idx)
        _win = form_src[_idx:_end if _end != -1 else _idx + 400]
        check_true("★ '면적 조건' 은 이제 실제 입력이다('준비 중입니다' 가 아니다)",
                   "준비 중입니다" not in _win,
                   "-> 백엔드는 min/max_building_area 를 받는데 화면에서 넣을 수 없다")
        check_true("'면적 조건' 이 건물/토지 두 범위를 모두 그린다",
                   "buildingAreaMin" in _win and "landAreaMin" in _win,
                   "-> 한쪽만 있으면 나머지 파라미터가 도달하지 못한다")

    # 자기 검증: 비교가 실제로 동작하는가(공허하지 않은가).
    check_true("자기 검증: 없는 키를 넣으면 잡힌다",
               ("qa_bogus_param" in ({"qa_bogus_param"} | frontend) - backend))
    check_true("자기 검증: 백엔드에 있는 키는 안 잡힌다",
               "sido" in backend and "sido" not in missing)



# 크롬 드라이버를 **직접** 만들어도 되는 곳. 이 둘만이 폴백을 들고 있는 자리다.
# 나머지 추적 파일은 전부 `crawler.base_crawler.resolve_chrome_driver()` 를 거쳐야
# 한다 - 직접 `ChromeDriverManager().install()` 을 부르면 Selenium Manager 폴백이
# 사라지고, 이 PC 에서는 그 순간 기동에 실패한다(BUGS #196).
CHROME_DRIVER_FALLBACK_OWNERS = {
    "crawler/base_crawler.py",  # 수집 파이프라인 전체가 여기를 쓴다
    "audit_viewport.py",        # 프런트 감사 도구의 같은 구조(BUGS #193)
}


def test_pipeline_resolves_chrome_driver_through_one_place():
    """수집 파이프라인이 크롬 드라이버를 얻는 경로가 하나인가 (BUGS #196).

    ## 왜 이 검사가 있는가 - 실제로 파이프라인 전체가 멈춰 있었다

    2026-08-25 실측: `crawler.base_crawler.build_driver()` 와
    `crawler.doc_crawler.build_download_driver()` 가 **둘 다** 1초 남짓 만에 실패했다.

        ConnectionError: Could not reach host. Are you offline?

    그런데 오프라인이 아니었다 - 같은 순간 같은 호스트에 stdlib urllib 로 HTTP 200 이
    0.05초에 왔다. `webdriver_manager` 가 쓰는 `requests` 경로의 CA 검증만 깨져 있었고
    (`SSLCertVerificationError: unable to get local issuer certificate`),
    그 예외가 "오프라인이냐"로 바뀌어 나왔다.

    영향이 크다 - `docs/BETA_RELEASE_CHECKLIST.md` 가 P0-A 의 **1순위 조치**로 적어 둔
    "스케줄러 등록"을 해도, 그날 밤 크롤과 DocWorker 는 브라우저를 못 띄우고 죽는다.
    그리고 로그에 남는 문장이 "오프라인이냐"라서 조사하는 사람은 멀쩡한 네트워크를 뒤진다.

    ## 무엇을 검사하는가

    1. 파이프라인 파일들이 `ChromeDriverManager` 를 **직접** 부르지 않는다
       (유일한 예외는 `crawler/base_crawler.py` 의 폴백 함수 안이다).
    2. `resolve_chrome_driver()` 가 순서/폴백/실패보고를 실제로 한다 - 가짜 factory 를
       주입해 **브라우저 없이** 확인한다.
    """
    import ast

    print("\n--- 수집 파이프라인의 크롬 드라이버 해석 경로 (BUGS #196) ---")
    root = os.path.dirname(os.path.abspath(__file__))

    # ★ 목록을 손으로 들지 않는다 - 새 스크립트가 추가되면 목록이 낡는다.
    #   `git ls-files` 로 **추적된 파이썬 전부**를 훑는다.
    try:
        ls = subprocess.run(["git", "ls-files", "*.py"], cwd=root,
                            capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print("[SKIP] git 을 실행할 수 없다 (%s)" % type(exc).__name__)
        return
    if ls.returncode != 0:
        print("[SKIP] git 저장소가 아니다")
        return
    tracked = (ls.stdout or b"").decode("utf-8", "replace").split()
    check_true("검사가 공허하지 않다(추적 파이썬 파일이 있다) - %d개" % len(tracked),
               len(tracked) >= 40, len(tracked))

    offenders = []
    for rel in tracked:
        if rel in CHROME_DRIVER_FALLBACK_OWNERS:
            continue
        if is_onedrive_conflict(rel):
            continue          # 제품이 아니다 — 전용 검사가 따로 센다(#253)
        full = os.path.join(root, rel.replace("/", os.sep))
        try:
            tree = ast.parse(open(full, encoding="utf-8-sig").read())
        except (OSError, SyntaxError):
            continue          # 작업 트리에 없거나 파싱 불가 - 판정 대상이 아니다
        for node in ast.walk(tree):
            # 호출만 본다 - 주석/문자열에 이름이 나오는 것은 결함이 아니다.
            if not isinstance(node, ast.Call):
                continue
            fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if fname == "ChromeDriverManager":
                offenders.append("%s:%d" % (rel, node.lineno))

    check("★ 드라이버를 직접 만드는 파일(폴백 보유자 제외)", sorted(offenders), [])
    if offenders:
        print("      -> `from crawler.base_crawler import resolve_chrome_driver` 를 쓰라."
              " 직접 부르면 Selenium Manager 폴백이 사라져 이 PC 에서 기동에 실패한다")
    for owner in sorted(CHROME_DRIVER_FALLBACK_OWNERS):
        check_true("폴백 보유자 %s 가 추적된다" % owner, owner in tracked)

    # base_crawler 는 폴백을 **실제로 갖고 있어야** 한다 (없애면 위 검사는 여전히 초록이다)
    bc = open(os.path.join(root, "crawler", "base_crawler.py"), encoding="utf-8-sig").read()
    bc_tree = ast.parse(bc)
    names = {n.name for n in bc_tree.body if isinstance(n, ast.FunctionDef)}
    check_true("base_crawler 에 resolve_chrome_driver() 가 있다",
               "resolve_chrome_driver" in names, sorted(names))
    check_true("폴백이 둘 이상이다(Selenium Manager + webdriver_manager)",
               bc.count("(\"Selenium Manager\"") == 1 and bc.count("(\"webdriver_manager\"") == 1,
               "-> CHROME_DRIVER_FACTORIES 가 한 가지로 줄면 이 PC 에서 다시 못 띄운다")

    # --- 행위 검사: 가짜 factory 주입 (브라우저를 띄우지 않는다) -------------
    sys.path.insert(0, root)
    from crawler.base_crawler import resolve_chrome_driver, DriverUnavailable

    calls = []

    def ok_factory(tag):
        def make(opts):
            calls.append(tag)
            return "driver-%s" % tag
        return make

    def bad_factory(tag, message):
        def make(opts):
            calls.append(tag)
            raise RuntimeError(message)
        return make

    def try_resolve(factories):
        """예외를 값으로 바꾼다 - 회귀가 트레이스백으로 나오면 어느 단언이 깨졌는지 모른다."""
        try:
            return resolve_chrome_driver(None, factories=factories), None
        except Exception as exc:
            return None, "%s: %s" % (type(exc).__name__, exc)

    del calls[:]
    drv, why = try_resolve([("A", ok_factory("A")), ("B", ok_factory("B"))])
    check("첫 방법이 되면 두 번째는 부르지 않는다", calls, ["A"])
    check("첫 방법이 돌려준 것을 쓴다", drv, "driver-A")

    del calls[:]
    drv, why = try_resolve([("A", bad_factory("A", "SSL 실패")), ("B", ok_factory("B"))])
    check("첫 방법이 실패하면 폴백으로 넘어간다", calls, ["A", "B"])
    check("폴백이 돌려준 것을 쓴다", drv, "driver-B")

    del calls[:]
    drv, why = try_resolve([("A", bad_factory("A", "SSL 실패")),
                            ("B", bad_factory("B", "경로 없음"))])
    check_true("전부 실패하면 DriverUnavailable 이다",
               drv is None and why is not None and why.startswith("DriverUnavailable:"), why)
    check_true("실패 사유에 두 방법이 모두 들어 있다",
               why is not None and "A ->" in why and "B ->" in why, why)
    check_true("실패 사유에 원래 메시지가 남는다",
               why is not None and "SSL 실패" in why and "경로 없음" in why, why)

    # 자기 검증: 이 행위 검사가 공허하지 않다.
    check_true("자기 검증: 성공/폴백/전멸이 실제로 다르게 나온다",
               len({try_resolve([("A", ok_factory("A"))])[0],
                    try_resolve([("A", bad_factory("A", "x")), ("B", ok_factory("B"))])[0],
                    try_resolve([("A", bad_factory("A", "x"))])[0]}) == 3)



def test_no_python_syntax_warnings():
    """추적된 파이썬이 컴파일 단계에서 **경고를 내지 않는가** (2026-08-25, BUGS #204).

    ## 왜 이것이 소음 이상인가

    `invalid escape sequence '\\d'` 는 대개 둘 중 하나다.

        (a) 문서/주석에 Windows 경로를 raw 아닌 문자열로 적었다  -> 무해하지만 소음
        (b) **정규식을 raw 문자열로 안 썼다**                    -> 패턴이 조용히 달라진다

    (b) 는 이 저장소가 반복해서 잡아 온 "조용히 틀린 것"이다. 지금은 (a) 한 건이었고
    고쳤지만(`test_asset_record_failures.py` 의 모듈 docstring 에 `storage\\database.py`
    가 들어 있었다), **구분해서 막을 방법이 없으므로 둘 다 막는다.**

    소음 자체도 값이다 — 이 저장소는 판정 신호를 흐리는 것을 계속 걷어내 왔다
    (`run_python_tests.py` 의 NO-VERDICT 분류가 같은 취지다). 매 실행마다 나오는 경고는
    **진짜 경고가 났을 때 눈에 안 띄게** 만든다.
    """
    print("\n--- 추적 파이썬의 컴파일 경고 (BUGS #204) ---")
    import io as _io
    import warnings as _warnings

    root = os.path.dirname(os.path.abspath(__file__))
    try:
        ls = subprocess.run(["git", "ls-files", "*.py"], cwd=root,
                            capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print("[SKIP] git 을 실행할 수 없다 (%s)" % type(exc).__name__)
        return
    if ls.returncode != 0:
        print("[SKIP] git 저장소가 아니다")
        return
    files = (ls.stdout or b"").decode("utf-8", "replace").split()
    check_true("검사가 공허하지 않다(추적 .py 를 찾았다) - %d개" % len(files),
               len(files) >= 40, len(files))

    offenders = []
    for rel in files:
        full = os.path.join(root, rel.replace("/", os.sep))
        try:
            src = _io.open(full, encoding="utf-8-sig").read()
        except OSError:
            continue          # 작업 트리에 없는 것은 판정 대상이 아니다
        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always")
            try:
                compile(src, rel, "exec")
            except SyntaxError:
                continue      # 문법 오류는 다른 검사의 몫이다
            for w in caught:
                if issubclass(w.category, SyntaxWarning):
                    offenders.append("%s:%s %s" % (rel, w.lineno, str(w.message)[:60]))

    check("★ 컴파일 경고를 내는 추적 파일", sorted(offenders), [])
    if offenders:
        print("      -> 정규식이면 raw 문자열(r\"...\")로, 문서에 든 경로면 docstring 을")
        print("         raw 로 만들라. 텍스트를 고치지 말고 리터럴만 바꾸는 편이 안전하다")

    # 자기 검증 - 이 검사가 실제로 경고를 잡는가(공허하지 않은가)
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        compile('x = "\\d"\n', "<probe>", "exec")
        probe = [w for w in caught if issubclass(w.category, SyntaxWarning)]
    check_true("자기 검증: 일부러 만든 잘못된 이스케이프를 잡는다", len(probe) == 1, probe)

def run():
    test_get_connection_fk_parameter()
    test_soft_delete_columns()
    test_migration_history_complete()
    test_requirements_covers_all_imports()
    test_error_codes_defined_documented_emitted()
    test_frontend_labels_cover_backend_enums()
    test_frontend_court_list_matches_backend_master()
    test_storage_sources_are_tracked()
    test_tracked_sources_do_not_import_untracked()
    test_no_new_duplicate_indexes()
    test_no_new_tracked_but_ignored_files()
    test_migration_runner_skip_and_failure()
    test_code_dependent_unique_constraints()
    test_powershell_scripts_have_bom()
    test_source_bom_matches_head()
    test_court_list_integrity()
    test_init_db_upgrades_old_schema()
    test_api_never_reads_legacy_doc_flags()
    test_list_gets_never_return_success_false()
    test_no_confusable_column_misuse()
    test_no_new_sql_text_interpolation()
    test_sql_placeholder_sites_are_bounded_or_chunked()
    test_init_db_failure_is_loud()
    test_known_dependency_cves_are_tracked()
    test_no_duplicate_config_constants()
    test_config_constants_match_their_copies()
    test_no_escape_corrupted_text()
    test_crlf_blobs_are_not_rewritten_as_lf()
    test_no_live_unreachable_claim_about_version_log()
    test_no_cwd_relative_paths_in_product_code()
    test_claude_md_scheduler_claims_match_register_script()
    test_root_scripts_do_not_write_db_without_apply()
    test_no_hardcoded_foreign_machine_paths()
    test_scheduler_script_detects_legacy_tasks()
    test_claude_md_paths_exist()
    test_no_new_tracked_sqlite_databases()
    test_entrypoints_do_not_attach_file_logs_on_import()
    test_search_form_params_reach_the_backend()
    test_pipeline_resolves_chrome_driver_through_one_place()
    test_no_python_syntax_warnings()
    test_declared_indexes_survive_bootstrap()
    test_secret_comparisons_are_constant_time()
    test_onedrive_conflict_copies_do_not_grow()
    test_product_module_names_are_not_shadowed_by_stale_copies()
    test_no_new_duplicate_product_symbols()
    test_rights_badges_do_not_render_unknown_as_zero()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0



# ---------------------------------------------------------------------------
# 소스가 만드는 인덱스가 **새 DB 에서 실제로 살아남는가** (2026-08-25 신설, BUGS #208)
#
# 왜 필요한가 — `013_auction_item_case_id_unique.sql` 은 `auction_item` 을 **재작성**한다
# (CREATE TABLE + INSERT INTO + DROP TABLE + ALTER TABLE RENAME). 그 과정에서 기존
# 인덱스는 전부 사라지고, 013 이 **하드코딩한 16개만** 다시 만들어진다.
#
# 그래서 013 보다 앞 번호 마이그레이션에 인덱스를 추가하면 **조용히 없어진다.**
# 실측(2026-08-25):
#
#     008_create_search_indexes.sql 에 CREATE INDEX 한 줄 추가
#     -> 부트스트랩 후 그 인덱스는 **존재하지 않는다** (013 이 지우고 안 만든다)
#     -> 오류도 경고도 없다
#
# 하필 그 파일 이름이 `create_search_indexes.sql` 이라, 검색이 느려서 인덱스를 넣으려는
# 사람이 가장 먼저 여는 곳이다.
#
# 그리고 이건 **로컬과 배포가 갈리는** 모양이다 - 013 이 이미 돌아간 운영 DB 는 마이그레이션이
# 다시 실행되지 않으므로 새로 추가한 인덱스가 그대로 남는다. 새로 클론한 개발 머신에는 없다.
# "여기선 되는데"가 되는 전형적인 자리다.
#
# 이 검사는 **소스에 선언된 모든 인덱스가 부트스트랩 결과에 실제로 있는지**를 본다.
# 013 에만 있는 문제가 아니라, 앞으로 어떤 마이그레이션이 어떤 테이블을 재작성해도 잡힌다.
# ---------------------------------------------------------------------------
def test_declared_indexes_survive_bootstrap():
    """소스가 CREATE INDEX 한 이름이 부트스트랩한 DB 에 전부 존재하는가 (BUGS #208)."""
    print("\n--- 선언한 인덱스가 새 DB 에서 살아남는다 (BUGS #208) ---")
    import contextlib
    import glob as _glob
    import io as _io
    import re as _re
    import sqlite3 as _sqlite3
    import tempfile

    root = os.path.dirname(os.path.abspath(__file__))
    sources = ([os.path.join(root, "storage", "migrate_v4_1.py")]
               + sorted(_glob.glob(os.path.join(root, "storage", "migrations", "*.sql"))))
    # ★ CREATE 만 세면 **일부러 지운 인덱스를 결손으로 오인한다** (2026-09-02).
    #
    #   이 검사는 `CREATE INDEX` 만 모아 "새 DB 에 다 있는가"를 봤다. 그러면 뒤 번호
    #   마이그레이션이 **의도적으로 DROP** 한 인덱스가 영원히 붉게 남는다.
    #
    #   지금까지 안 걸린 것은 규칙이 맞아서가 아니라 우연이다 — 021 이 지운 5개는
    #   선언이 `migrate_v4_1.py`(부트스트랩 스크립트) 에 있었고, 그때 **그 CREATE 줄을
    #   같이 지워서** 목록에서 빠졌다. 선언이 번호 마이그레이션(001/002/026)에 있으면
    #   그 수법을 쓸 수 없다 — 이미 적용된 파일을 나중에 고쳐 쓰는 셈이라 그 파일이
    #   과거에 한 일을 더는 설명하지 못한다.
    #
    #   그래서 **DROP 도 함께 읽어** 마지막 선언이 CREATE 인지 DROP 인지로 판정한다.
    #   실제로 걸린 사례: 027/029 가 idx_favorite_notes_user_id · idx_favorites_user_id ·
    #   idx_recent_items_user_id 를 재측정 후 지웠다(각 파일 머리말에 측정치 있음).
    #
    #   순서는 `sources` 의 순서 = 부트스트랩 순서 = 번호순이므로, 뒤에 오는 문장이 이긴다.
    declared = {}          # 인덱스 이름 -> (선언한 파일, 테이블)  ※ 살아 있어야 하는 것만
    dropped = {}           # 인덱스 이름 -> 지운 파일               ※ 없어야 하는 것
    for path in sources:
        try:
            src = _io.open(path, encoding="utf-8-sig").read()
        except OSError:
            continue
        # 주석 줄(`--`)은 판정에서 뺀다 - 마이그레이션 머리말이 되돌리는 방법으로
        # `CREATE INDEX ...` 를 적어 두는 관례가 있어서 그대로 세면 되살아난 것으로 읽힌다.
        body = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("--"))
        events = []
        for m in _re.finditer(
                r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r"[\"\[`]?(\w+)[\"\]`]?\s+ON\s+[\"\[`]?(\w+)", body, _re.I):
            events.append((m.start(), "create", m.group(1), m.group(2)))
        for m in _re.finditer(
                r"DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?[\"\[`]?(\w+)", body, _re.I):
            events.append((m.start(), "drop", m.group(1), None))
        for _pos, kind, name, table in sorted(events):
            if kind == "create":
                declared[name] = (os.path.basename(path), table)
                dropped.pop(name, None)
            else:
                dropped[name] = os.path.basename(path)
                declared.pop(name, None)

    check_true("검사가 공허하지 않다(소스에서 인덱스 선언을 찾았다) - %d개" % len(declared),
               len(declared) >= 40, len(declared))

    import storage.database as db
    prev = db.DB_PATH
    tmp = tempfile.mkdtemp(prefix="qa-idxsurvive-")
    try:
        db.DB_PATH = os.path.join(tmp, "auction.db")
        import storage.migrate_v4_1 as mig
        import storage.migrations.run_migrations as runmig
        # 부트스트랩 로그가 판정 줄을 덮지 않게 삼킨다(실패는 예외로 드러난다)
        with contextlib.redirect_stdout(_io.StringIO()):
            db.init_db(); mig.migrate(); runmig.run()
        conn = _sqlite3.connect(db.DB_PATH)
        try:
            live = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")}
        finally:
            conn.close()
    finally:
        db.DB_PATH = prev

    check_true("검사가 공허하지 않다(부트스트랩 DB 에 인덱스가 있다) - %d개" % len(live),
               len(live) >= 40, len(live))

    missing = sorted((n, declared[n][0], declared[n][1]) for n in declared if n not in live)
    if missing:
        for n, f, t in missing:
            print("      [사라짐] %-40s %s 가 %s 에 만들지만 새 DB 에 없다" % (n, f, t))
    check_true("★ 소스가 선언한 인덱스가 새 DB 에 전부 존재한다", not missing,
               "-> %s. 뒤 번호 마이그레이션이 그 테이블을 **재작성**하면서 인덱스를 "
               "다시 만들지 않았을 가능성이 크다(013 이 auction_item 에 대해 그렇게 한다). "
               "재작성하는 마이그레이션의 CREATE INDEX 목록에도 함께 넣으라 (BUGS #208)"
               % [n for n, _f, _t in missing])

    # 반대 방향 — DROP 을 읽기 시작했으니 **그게 면죄부가 되지 않는지**도 봐야 한다.
    # 지웠다고 선언한 인덱스가 새 DB 에 그대로 있으면, 그 DROP 이 실제로는 안 돈 것이다
    # (뒤 마이그레이션이 테이블을 재작성하며 되살렸거나, 이름을 잘못 적었거나).
    resurrected = sorted((n, f) for n, f in dropped.items() if n in live)
    if resurrected:
        for n, f in resurrected:
            print("      [되살아남] %-40s %s 가 지웠는데 새 DB 에 있다" % (n, f))
    check_true("★ 지웠다고 선언한 인덱스가 새 DB 에 없다", not resurrected,
               "-> %s" % [n for n, _f in resurrected])
    check_true("검사가 공허하지 않다(DROP 선언을 실제로 찾았다) - %d개" % len(dropped),
               len(dropped) >= 3, sorted(dropped))

    # 자기 검증 - 이 검사가 실제로 "사라짐"을 잡는가(공허하지 않은가).
    #   소스 파일을 건드리지 않고, 선언 목록에 없는 이름을 하나 끼워 넣어 판정만 흉내 낸다.
    fake = dict(declared)
    fake["idx_qa_probe_never_created"] = ("probe", "auction_item")
    probe_missing = [n for n in fake if n not in live]
    # 진짜 결손이 있을 때 이 자기 검증까지 함께 붉어지면 원인 줄이 두 배가 된다.
    # "탐지기가 동작하는가"만 본다 - 실제 결손 여부는 위 검사가 판정한다.
    check_true("자기 검증: 없는 인덱스를 잡는다",
               "idx_qa_probe_never_created" in probe_missing, probe_missing)


# ---------------------------------------------------------------------------
# 시크릿 비교가 **상수 시간**인가 (2026-08-25 신설, BUGS #209)
#
# 왜 구조로 보는가 — 이건 **행위로 잡을 수 없다.** `==` 로 바꿔도 응답은 완전히 같다.
# 다른 점은 "얼마나 걸리느냐"뿐이고, 그 차이는 단위 테스트에서 안정적으로 측정되지 않는다.
#
# 실측(2026-08-25 mutation): `hmac.compare_digest` 를 `==` 로 바꿔도
#
#     api/v1/payment_providers.py  verify_webhook_signature   실패 0건
#     api/v1/admin.py              resolve_admin_role         실패 0건
#         (test_admin_secret_contract / test_api_regression / test_schema_hygiene 전부)
#
# 즉 **네 자리 전부 무방비**였다. 같은 파일의 주석이 왜 상수 시간이어야 하는지
# 이미 적어 두고 있는데(`api/v1/admin.py`: *"단순 `!=`는 앞에서부터 다르면 즉시 반환되어
# 비교 시간이 일치하는 접두 길이에 비례하는 타이밍 사이드채널이 된다"*), 그 판단을
# 지키는 것이 없었다. BUGS #207 과 같은 모양이다 — 제품은 옳은데 가드가 없다.
#
# 두 겹으로 본다.
#   (1) 아는 자리들이 여전히 compare_digest 를 쓰는가
#   (2) **새로** 시크릿을 읽고 비교하는 함수가 생겼는데 목록에 없지는 않은가
# ---------------------------------------------------------------------------

# 값이 새면 곧바로 권한/결제 위조가 되는 환경변수들.
SECRET_ENV_NAMES = frozenset({
    "ADMIN_API_KEY", "SUPER_ADMIN_API_KEY",
    "PAYMENT_WEBHOOK_SECRET", "SUPABASE_JWT_SECRET",
})

# 그 값을 실제로 **비교**하는 함수 (2026-08-25 실측 기준).
# 늘어나면 아래 (2) 가 지목한다 - 그때 이 목록에 넣고 compare_digest 를 쓰라.
SECRET_COMPARING_FUNCTIONS = {
    ("api/v1/admin.py", "resolve_admin_role"),
    # 클래스 안의 메서드는 **클래스까지** 적는다 - 같은 이름의 기반 클래스 스텁
    # (`PaymentProvider.verify_webhook_signature`, 항상 False)이 먼저 잡혀
    # 엉뚱한 것을 검사하던 것을 2026-08-25 에 고쳤다.
    ("api/v1/payment_providers.py", "MockProvider.verify_webhook_signature"),
}


def _secret_env_reads(fn):
    """함수 안에서 os.getenv(<시크릿 이름>) 을 읽는가."""
    names = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "getenv" and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in SECRET_ENV_NAMES):
            names.add(node.args[0].value)
    return names


def _uses_compare_digest(fn):
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "compare_digest":
                return True
            if isinstance(f, ast.Name) and f.id == "compare_digest":
                return True
    return False


def _naive_equality_on(fn, targets):
    """`==`/`!=` 로 대상 이름을 직접 비교하는 자리를 찾는다(리터럴 비교는 뺀다)."""
    bad = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(o, (ast.Eq, ast.NotEq)) for o in node.ops):
            continue
        sides = [node.left] + list(node.comparators)
        # 한쪽이라도 리터럴이면 시크릿 대조가 아니다(예: name == "mock", x == "")
        if any(isinstance(s, ast.Constant) for s in sides):
            continue
        ids = {s.id for s in sides if isinstance(s, ast.Name)}
        if ids & targets:
            bad.append((getattr(node, "lineno", "?"), sorted(ids & targets)))
    return bad


def _secret_derived_locals(fn):
    """시크릿에서 유래한 지역 이름 - os.getenv(...) 결과와 hexdigest() 결과."""
    out = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            v = node.value
            if (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                    and v.func.attr in ("getenv", "hexdigest")):
                out.add(node.targets[0].id)
    return out


def test_secret_comparisons_are_constant_time():
    """시크릿 비교가 `hmac.compare_digest` 로 이뤄지는가 (BUGS #209)."""
    print("\n--- 시크릿 비교가 상수 시간이다 (BUGS #209) ---")
    import glob as _glob
    import io as _io

    root = os.path.dirname(os.path.abspath(__file__))
    product = ([p for p in _glob.glob(os.path.join(root, "api", "**", "*.py"), recursive=True)]
               + [p for p in _glob.glob(os.path.join(root, "storage", "**", "*.py"),
                                        recursive=True)])
    trees = {}
    for path in product:
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            trees[rel] = ast.parse(_io.open(path, encoding="utf-8-sig").read())
        except (OSError, SyntaxError):
            continue
    check_true("검사가 공허하지 않다(제품 소스를 파싱했다) - %d개" % len(trees),
               len(trees) >= 10, len(trees))

    def find_fn(rel, name):
        """`함수` 또는 `클래스.메서드` 를 찾는다."""
        tree = trees.get(rel)
        if tree is None:
            return None
        if "." in name:
            cls_name, meth = name.split(".", 1)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == cls_name:
                    for sub in node.body:
                        if isinstance(sub, ast.FunctionDef) and sub.name == meth:
                            return sub
            return None
        for node in tree.body:            # 최상위 함수만 - 메서드는 위에서 처리한다
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None

    # (1) 아는 자리가 여전히 상수 시간인가
    for rel, name in sorted(SECRET_COMPARING_FUNCTIONS):
        fn = find_fn(rel, name)
        check_true("검사가 공허하지 않다(%s 의 %s() 를 찾았다)" % (rel, name), fn is not None,
                   "-> 이름이 바뀌었으면 SECRET_COMPARING_FUNCTIONS 도 고쳐라")
        if fn is None:
            continue
        check_true("★ %s: %s() 가 hmac.compare_digest 를 쓴다" % (rel, name),
                   _uses_compare_digest(fn),
                   "-> `==` 로 시크릿을 비교하면 앞에서부터 다를 때 즉시 반환돼 "
                   "**일치하는 접두 길이에 비례하는 타이밍 차이**가 생긴다. "
                   "응답은 똑같으므로 행위 검사로는 잡히지 않는다 (BUGS #209)")
        # 시크릿에서 온 지역 이름을 `==` 로 직접 대조하지는 않는가
        secret_locals = _secret_derived_locals(fn)
        naive = _naive_equality_on(fn, secret_locals)
        check_true("%s: %s() 가 시크릿을 `==` 로 대조하지 않는다" % (rel, name),
                   not naive, "-> %s" % naive)

    # (2) 새로 생긴 비교 자리가 목록 밖에 있지는 않은가
    #
    #     "시크릿을 읽는다"만으로는 부족하다 - `_require_role()` 처럼 **설정 여부만**
    #     보는 함수도 걸려 오탐이 된다(2026-08-25 실측). 실제로 **대조하는** 함수만 센다:
    #     compare_digest 를 쓰거나, 시크릿에서 온 이름을 `==` 로 맞대는 함수.
    unlisted = []
    for rel, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not _secret_env_reads(node):
                continue
            secret_locals = _secret_derived_locals(node)
            compares_secret = bool(_naive_equality_on(node, secret_locals))
            if not (compares_secret or _uses_compare_digest(node)):
                continue                  # 존재 확인만 하는 함수 - 대상이 아니다
            listed = any(node.name == n.split(".")[-1]
                         for r, n in SECRET_COMPARING_FUNCTIONS if r == rel)
            if not listed:
                unlisted.append("%s:%s" % (rel, node.name))
    check_true("★ 시크릿을 비교하는데 목록에 없는 함수가 없다", not unlisted,
               "-> %s. 시크릿 대조라면 hmac.compare_digest 를 쓰고 "
               "SECRET_COMPARING_FUNCTIONS 에 넣으라. 대조가 아니라면 왜 아닌지를 "
               "여기 주석으로 남기라 (BUGS #209)" % sorted(set(unlisted)))
    # 자기 검증 - 이 분석이 실제로 `==` 대조를 잡는가(공허하지 않은가)
    probe = ast.parse(
        "def f():\n"
        "    k = os.getenv('ADMIN_API_KEY', '')\n"
        "    return given == k\n")
    pfn = probe.body[0]
    check_true("자기 검증: 합성 `==` 대조를 잡는다",
               not _uses_compare_digest(pfn) and _naive_equality_on(pfn, {"k"}),
               "-> 탐지기가 동작하지 않는다")



def test_onedrive_conflict_copies_do_not_grow():
    """OneDrive 충돌 사본을 **따로 세어** 눈에 띄게 남긴다 (2026-08-27, BUGS #253).

    위 제품 검사들에서 뺀 것을 여기서 갚는다 — 숨기는 것이 아니라 옮기는 것이다.
    """
    print("\n--- OneDrive 충돌 사본 (제품 아님 / 사람이 정리할 부채) ---")
    root = os.path.dirname(os.path.abspath(__file__))
    try:
        ls = subprocess.run(["git", "ls-files", "-z"], cwd=root,
                            capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print("[SKIP] git 을 실행할 수 없다 (%s)" % type(exc).__name__)
        return
    if ls.returncode != 0:
        print("[SKIP] git 저장소가 아니다")
        return
    paths = [p.decode("utf-8", "replace") for p in ls.stdout.split(b"\x00") if p]
    conflicts = sorted(p for p in paths if is_onedrive_conflict(p))

    # 검사가 공허하지 않다 — 판별기가 실제로 무언가를 구별하는가.
    check_true("자기 검증: 충돌 사본 이름을 잡는다",
               is_onedrive_conflict("test_x-DESKTOP-DVRJEGP.py"))
    check_true("자기 검증: 커버리지 산출물 이름도 잡는다",
               is_onedrive_conflict(".cov_test_x-DESKTOP-DVRJEGP_py"))
    check_true("자기 검증: 평범한 제품 파일은 안 잡는다",
               not is_onedrive_conflict("storage/database.py"))

    for c in conflicts:
        print("      (부채) %s" % c)
    check_true("★ OneDrive 충돌 사본이 늘지 않았다 (현재 %d개, 상한 %d개)"
               % (len(conflicts), KNOWN_ONEDRIVE_CONFLICTS),
               len(conflicts) <= KNOWN_ONEDRIVE_CONFLICTS,
               "-> %s" % conflicts)
    if conflicts:
        print("      -> 정리는 사람이 한다: 각 쌍에서 어느 쪽이 최신인지 고른 뒤"
              " `git rm --cached` 로 추적에서 뺀다. 자동으로 지우지 않는다.")


# ---------------------------------------------------------------------------
# 제품 모듈 이름을 **가리는 낡은 사본**이 있는가 (2026-08-27, docs/BUGS.md #262)
#
# 실측: `logs/` 안에 2026-08-04 자 사본 세 개가 있다.
#
#     logs/mvp_scraper.py       130줄   (제품은 321줄)
#     logs/doc_worker.py
#     logs/refresh_priority.py
#
# 추적되지 않고(`.gitignore`) 3주 넘게 방치된 초기 판본이다. 왜 위험한가:
#
#   [1] 이 저장소의 진단 스크립트 다수가 `sys.path.insert(0, os.getcwd())` 를 쓴다.
#       `logs/` 에서 그런 스크립트를 돌리면 **3주 전 mvp_scraper 를 import 한다.**
#       그리고 그 판본에는 이 세션이 고친 것들이 하나도 없다.
#   [2] 더 흔한 피해는 사람이다 — 장애를 쫓다 `logs/mvp_scraper.py` 를 열고
#       "제품이 이렇게 돼 있네" 라고 읽는다. 그 파일은 제품이 아니다.
#
# `-DESKTOP-*` 충돌 사본(#253)과 **같은 부류**다: 제품 파일의 옛 판본이 제품 이름으로
# 남아 있다. 그래서 처리도 같게 한다 — **지우지 않고**(파일 삭제는 승인 영역,
# docs/CLAUDE.md) 목록을 찍고 **늘어나면 붉어지게** 한다.
#
# ★ `__pycache__` 는 세지 않는다 - 파이썬이 만드는 것이고 이름이 가려지지도 않는다.
# ---------------------------------------------------------------------------
# 제품 모듈 이름이 나타나면 안 되는 폴더. 전부 산출물 폴더다(코드가 살 자리가 아니다).
SHADOW_SCAN_DIRS = ("logs", "downloads", "documents", "documents_quarantine",
                    "registry_documents", "public")

# 지금 알고 있는 그림자 사본 수. 늘어나면 붉어진다(줄어드는 것은 정리이므로 통과다).
KNOWN_SHADOW_COPIES = 3


def test_product_module_names_are_not_shadowed_by_stale_copies():
    print("\n--- 산출물 폴더에 제품 모듈 이름의 낡은 사본이 있는가 (BUGS #262) ---")
    root = os.path.dirname(os.path.abspath(__file__))

    # 제품 모듈 이름 = 저장소 루트의 추적된 .py + 제품 패키지 폴더 이름
    try:
        ls = subprocess.run(["git", "ls-files", "-z"], cwd=root,
                            capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print("[SKIP] git 을 실행할 수 없다 (%s)" % type(exc).__name__)
        return
    if ls.returncode != 0:
        print("[SKIP] git 저장소가 아니다")
        return
    tracked = [p.decode("utf-8", "replace")
               for p in ls.stdout.split(b"\x00") if p]
    product_names = set()
    for rel in tracked:
        if rel.endswith(".py") and "/" not in rel and not rel.startswith("test_"):
            product_names.add(os.path.basename(rel))
    check_true("검사가 공허하지 않다(제품 모듈 이름을 실제로 모았다)",
               len(product_names) > 5, sorted(product_names)[:8])
    check_true("검사가 공허하지 않다(대표 모듈이 목록에 있다)",
               "mvp_scraper.py" in product_names and "doc_worker.py" in product_names,
               sorted(product_names)[:8])

    shadows = []
    scanned = 0
    for d in SHADOW_SCAN_DIRS:
        base = os.path.join(root, d)
        if not os.path.isdir(base):
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = [x for x in dn if x != "__pycache__"]
            scanned += 1
            for f in fn:
                if f in product_names:
                    rel = os.path.relpath(os.path.join(dp, f), root)
                    shadows.append(rel.replace(os.sep, "/"))
    check_true("검사가 공허하지 않다(산출물 폴더를 실제로 훑었다)", scanned > 0, scanned)

    import io as _io
    for sfile in sorted(shadows):
        full = os.path.join(root, sfile.replace("/", os.sep))
        try:
            lines = sum(1 for _ in _io.open(full, encoding="utf-8", errors="replace"))
        except OSError:
            lines = -1
        print("      (부채) %-40s %d줄" % (sfile, lines))
    check_true("★ 제품 이름을 가리는 사본이 늘지 않았다 (현재 %d개, 상한 %d개)"
               % (len(shadows), KNOWN_SHADOW_COPIES),
               len(shadows) <= KNOWN_SHADOW_COPIES, "-> %s" % sorted(shadows))
    if shadows:
        print("      -> 정리는 사람이 한다(파일 삭제는 승인 영역). 위험한 이유는"
              " 진단 스크립트 다수가 sys.path 에 cwd 를 넣기 때문이다 -"
              " 그 폴더에서 실행하면 낡은 판본을 import 한다.")

    # ── 2026-09-01 추가: 위험이 import 만이 아니다 — **그냥 실행된다** ──────────
    #
    #   #262 는 이 사본들을 "sys.path 오염으로 낡은 판본을 import 하게 되는 것"으로
    #   설명한다. 맞지만 절반이다. 실측하니 `logs/mvp_scraper.py` 는 import 가 깨져
    #   있지 않다(`get_courts_by_region` 은 지금도 있다). 즉 `python logs/mvp_scraper.py`
    #   가 **그대로 돌아 실제 크롤을 하고 실제 DB 에 upsert 한다.**
    #
    #   그리고 그 사본들에는 **RunLock 이 없다**(2026-08-03 판본. 락은 그 뒤에 붙었다).
    #   Sprint 246 이 "락 파일이 갈라지면 중복 실행 방지가 조용히 무력화된다"고 실측해
    #   둔 상황을, 락 자체가 없는 사본은 더 쉽게 만든다 — 예약 크롤과 동시에 돈다.
    #
    #   그래서 "몇 개인가" 옆에 **"얼마나 낡았는가"** 를 함께 못박는다. 누가 사본을
    #   최신 내용으로 덮어쓰면 이 항목의 성격이 달라지므로 그때 다시 판단해야 한다.
    stale_evidence = []
    for sfile in sorted(shadows):
        base = os.path.basename(sfile)
        origin = os.path.join(root, base)
        if not os.path.exists(origin):
            continue
        try:
            copy_src = open(os.path.join(root, sfile.replace("/", os.sep)),
                            encoding="utf-8", errors="replace").read()
            orig_src = open(origin, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "RunLock" in orig_src and "RunLock" not in copy_src:
            stale_evidence.append(sfile)
    check("★ 사본 중 RunLock 이 빠진 것(중복 실행 방지가 없는 판본)",
          stale_evidence, ["logs/doc_worker.py", "logs/mvp_scraper.py"])
    if stale_evidence:
        print("      -> 이 사본들은 **실행 가능하고 락이 없다.** 예약 크롤과 동시에"
              " 돌 수 있다. 지우는 것은 사람의 판단이다(#253 과 같은 이유)")



# ---------------------------------------------------------------------------
# 제품 코드에 **같은 이름의 최상위 심볼**이 새로 생기지 않는가 (2026-09-02 신설)
#
# Frankenstein 전수 감사에서 나왔다. 같은 이름의 함수가 여러 제품 모듈에 있으면
# **잘못 가져다 쓰기 쉽고, 그러면 같은 개념이 경로마다 다르게 계산된다.**
# 이 저장소가 반복해서 겪은 모양이다:
#
#     normalize_case_no   normalizer.py(크롤: 원천 보존) vs mylist_import.py(가져오기: 추출)
#                         -> 잘못 합치면 '2024타채1009' 가 **빈 문자열**이 된다
#     get_doc_dir         doc_paths.py(만든다) vs api/v1/documents.py(조회만)
#                         -> 잘못 합치면 조회가 디렉터리를 만든다(실제로 겪었다, 빈 폴더 1,675개)
#     row_to_subscription payments.py(기본 9필드) vs subscriptions.py(+파생 3)
#                         -> 한쪽만 필드가 늘면 같은 엔티티가 두 모양으로 나간다
#
# 셋 다 **지금은 정당한 이유가 있어 남겨 둔** 것이고, 각각 별도 검사가 계약을 고정하고
# 있다(`test_normalizer.py` / `test_doc_path_safety.py` / `test_subscription_policy.py`).
# 그래서 여기서는 지우라고 하지 않는다 — **새로 늘어나는 것만** 막는다.
#
# 2026-09-02 실측: 제품 모듈 69개에서 중복 이름 11건. 그중 `main` 은 스크립트마다
# 하나씩 있는 진입점이라 세지 않는다.
#
# ★ 이 검사가 붉어졌을 때 할 일은 "허용목록에 추가"가 **아니다.** 먼저 물어야 한다:
#     - 같은 개념인가? -> 한쪽으로 합친다(정본은 한 곳).
#     - 다른 개념인가? -> **이름을 다르게 짓는다.**
#   그래도 이름이 같아야 할 이유가 있으면, 그 이유와 **계약을 고정하는 검사**를
#   함께 만든 뒤에 아래 목록에 넣는다. 위 셋이 전부 그렇게 되어 있다.
# ---------------------------------------------------------------------------
KNOWN_DUPLICATE_SYMBOLS = {
    # 이름                 : 왜 남아 있는가 / 계약을 고정하는 검사
    "normalize_case_no":    "크롤은 원천 보존 / 가져오기는 추출 - test_normalizer.py 가 고정",
    "get_doc_dir":          "쓰기는 만든다 / 조회는 계산만 - test_doc_path_safety.py 가 고정",
    "row_to_subscription":  "기본 9필드 동일 + 파생 3 - test_subscription_policy.py 가 고정",
    "build_driver":         "옵션만 다르고 드라이버 해석은 base_crawler 한 곳 - 바로 위 검사가 고정",
    "wait_loading":         "수동 진입점(collect_documents)과 크롤러의 별개 대기 규칙",
    "select_court":         "수동 진입점(collect_documents)과 크롤러의 별개 선택 규칙",
    "attach_file_log":      "진입점마다 로그 파일이 다르다 - test_entrypoints_... 가 고정",
    "extract_fail_count":   "filter_engine 은 어떤 진입점도 부르지 않는 진단 경로",
    "load_item":            "권리/명세 로더가 각자 다른 표를 읽는다",
    "purge_orphans":        "권리/명세 로더가 각자 다른 표를 지운다",
}


def test_no_new_duplicate_product_symbols():
    print("\n--- 제품 코드에 같은 이름의 최상위 심볼이 새로 생겼는가 ---")
    import ast as _ast
    import subprocess as _sp
    import collections as _collections

    root = os.path.dirname(os.path.abspath(__file__))
    try:
        out = _sp.run(["git", "ls-files", "*.py"], cwd=root,
                      capture_output=True, text=True, encoding="utf-8", timeout=30)
        tracked = [f for f in out.stdout.split() if f.endswith(".py")] if out.returncode == 0 else []
    except (OSError, _sp.SubprocessError):
        tracked = []

    # 제품 코드만 본다. 테스트/일회성 진단 스크립트는 이름이 겹쳐도 해가 없다.
    SCRIPT_PREFIXES = ("test_", "step", "check_", "patch_", "analyze_", "audit_",
                       "debug_", "verify_", "detect_", "backfill_", "repair_",
                       "cleanup_", "measure_", "reset_", "unlock_", "fix_",
                       "migrate_dryrun", "empty_doc_dirs", "add_test_queue",
                       "collect_documents" if False else "\0")

    def is_product(rel):
        base = os.path.basename(rel)
        if "-DESKTOP-" in rel:
            return False
        return not base.startswith(SCRIPT_PREFIXES)

    product = [f for f in tracked if is_product(f)]
    check_true("제품 모듈을 실제로 모았다 - %d개" % len(product), len(product) >= 30, len(product))

    seen = _collections.defaultdict(list)
    for rel in product:
        path = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.exists(path):
            continue
        try:
            tree = _ast.parse(codecs.open(path, encoding="utf-8-sig").read())
        except SyntaxError:
            continue
        for node in tree.body:              # 모듈 최상위만 - 메서드는 클래스가 갈라 준다
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                if node.name.startswith("_") or node.name == "main":
                    continue                # main 은 스크립트마다 있는 진입점이다
                seen[node.name].append(rel)

    dupes = {n: locs for n, locs in seen.items() if len(locs) > 1}
    check_true("탐지기가 실제로 심볼을 모았다 - %d개" % len(seen), len(seen) >= 100, len(seen))

    unexpected = {n: locs for n, locs in dupes.items() if n not in KNOWN_DUPLICATE_SYMBOLS}
    check("새로 생긴 중복 심볼 없음", sorted(unexpected), [])
    if unexpected:
        for n, locs in sorted(unexpected.items()):
            print("      %s -> %s" % (n, " | ".join(locs)))
        print("      -> 합치거나 이름을 다르게 짓는다. 그래도 같아야 하면 계약 검사를"
              " 먼저 만들고 KNOWN_DUPLICATE_SYMBOLS 에 사유와 함께 넣는다.")

    # 허용목록이 **실측보다 헐거우면** 새 중복 하나가 조용히 들어와도 통과한다
    # (이 저장소가 상한 검사마다 지켜 온 규약).
    stale = sorted(n for n in KNOWN_DUPLICATE_SYMBOLS if n not in dupes)
    check("허용목록에 이미 해소된 이름이 남아 있지 않다", stale, [])
    if stale:
        print("      -> 위 이름은 더 이상 중복이 아니다. 목록에서 지워라.")

    print("    중복 %d건 (허용목록 %d건)" % (len(dupes), len(KNOWN_DUPLICATE_SYMBOLS)))



# ---------------------------------------------------------------------------
# 권리분석 배지가 **"모른다"를 "0"으로 말하지 않는가** (2026-09-02 신설)
#
# ## 왜 — 여기서 틀리면 사용자가 손해를 본다
#
# `rights_summary` 의 숫자 필드는 대부분 **생산자가 없어 항상 NULL** 이다
# (`test_pipeline_integrity.py` §15 가 목록을 고정한다). 화면이 그 NULL 을
# 숫자로 그리면 **"위험 임차인 0명" / "예상 인수금액 0원"** 처럼 보인다.
#
#     실제 뜻: "아직 판정하지 않았다"
#     화면의 뜻: "위험이 없다"
#
# 경매 물건의 권리관계에서 이 차이는 **사용자가 돈을 잃는 방향**이다. 오류도 빈
# 화면도 아니라서 아무도 신고하지 않는다 - 이 저장소가 "조용한 실패"라 부르는 것 중
# 결과가 가장 나쁜 쪽이다.
#
# ## 무엇을 고정하나
#
# 숫자/불리언 필드는 반드시 **`!= null` / `== null` 로 갈라야 한다.**
# 참/거짓(truthy) 검사는 **0 과 null 을 같은 것으로 뭉갠다**:
#
#     {n ? `${n}명` : '정보 없음'}        <- 0명인 물건이 "정보 없음" 이 된다 (거짓 음성)
#     {n ?? 0}명                          <- null 이 "0명" 이 된다 (거짓 안심) ★ 더 나쁘다
#     {n != null ? `${n}명` : '정보 없음'} <- 옳다
#
# 2026-09-02 실측: 상세화면의 세 숫자 필드가 전부 `!= null` / `== null` 을 쓰고 있다.
# 지금 옳다는 것과 앞으로도 지켜진다는 것은 다르므로 여기서 고정한다.
#
# 문자열 필드(`occupancy_status` 등)는 대상이 아니다 - 빈 문자열과 null 이 둘 다
# "모른다"라서 `||` 로 묶어도 뜻이 갈라지지 않는다.
# ---------------------------------------------------------------------------
RIGHTS_DETAIL_PAGE = "src/app/properties/[id]/page.tsx"

# 화면에 그려지는 rights_summary 의 **숫자/불리언** 필드.
# (문자열 필드는 위 주석의 이유로 제외한다.)
RIGHTS_NUMERIC_FIELDS = ("total_tenant_count", "is_vacant", "estimated_inheritance")


def test_rights_badges_do_not_render_unknown_as_zero():
    print("\n--- 권리분석 배지가 '모른다'를 '0'으로 말하지 않는가 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(root, RIGHTS_DETAIL_PAGE.replace("/", os.sep))
    if not os.path.exists(path):
        check_true("상세화면 파일이 있다 (%s)" % RIGHTS_DETAIL_PAGE, False, path)
        return
    src = codecs.open(path, encoding="utf-8-sig").read()
    check_true("검사가 공허하지 않다(상세화면을 실제로 읽었다)", len(src) > 1000, len(src))

    unguarded = []
    missing = []
    for field in RIGHTS_NUMERIC_FIELDS:
        # 그 필드를 언급하는 줄만 본다.
        lines = [ln for ln in src.splitlines() if field in ln]
        if not lines:
            missing.append(field)
            continue
        # 렌더 줄(JSX 안)에 null 을 명시적으로 가르는 표현이 있어야 한다.
        rendered = [ln for ln in lines if "{" in ln and "rights_summary" in ln]
        if not rendered:
            continue          # 타입 선언에만 나오고 그리지 않는다면 대상 아님
        for ln in rendered:
            if ("!= null" not in ln) and ("== null" not in ln):
                unguarded.append("%s: %s" % (field, ln.strip()[:90]))

    check("전제: 검사 대상 필드를 화면에서 찾았다", missing, [])
    check("★ 숫자 권리분석 필드가 null 을 0 으로 뭉개지 않는다", unguarded, [])
    if unguarded:
        print("      -> `!= null` 로 갈라라. truthy/`?? 0` 은 '모른다'를 '0'으로 바꾼다.")

    # 생산자가 없는 필드는 **화면 타입에조차 없어야** 한다.
    # 있으면 언젠가 그려지고, 그리는 순간 항상 빈 배지/0 이 된다.
    PRODUCERLESS_RIGHTS = ("dangerous_tenant_count", "total_deposit", "priority_right",
                           "lien_exists", "superficies_exists")
    leaked = sorted(f for f in PRODUCERLESS_RIGHTS if f in src)
    check("생산자 없는 권리 필드가 화면에 새어 들어오지 않았다", leaked, [])
    if leaked:
        print("      -> 이 필드는 항상 NULL 이다(§15). 그리려면 생산자부터 만들어야 한다.")

    # 탐지기 자기 검증 - 합성 입력에서 반드시 잡혀야 한다.
    bad_line = "{property.rights_summary.total_tenant_count ?? 0}명"
    check_true("탐지기 자기검증: `?? 0` 은 가드로 인정하지 않는다",
               ("!= null" not in bad_line) and ("== null" not in bad_line))
    good_line = "{property.rights_summary.total_tenant_count != null ? 'x' : 'y'}"
    check_true("탐지기 자기검증: `!= null` 은 가드로 인정한다", "!= null" in good_line)


if __name__ == "__main__":
    sys.exit(run())
