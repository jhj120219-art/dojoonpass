import sys, os, re
sys.path.insert(0, os.getcwd())
from storage.database import get_connection, requeue_changed_documents, chunked_for_sql
# 면적은 주소 원문에서 뽑는다. 추출 규칙의 **정본은 normalizer 한 곳**이다
# (백필 스크립트도 같은 함수를 쓴다 — 규칙이 두 벌이 되면 갈라진다, BUGS #204).
from normalizer.normalizer import extract_areas
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# migrate_execute 가 만드는 document_status 행의 종류.
#
# **이 목록이 단일 소스다.** 아래 §3 루프가 넣는 것도, 결과 검증이 세는 것도 여기서 온다.
# 두 곳에 따로 적으면 한쪽만 바뀌는 날이 오고, 그때 검증이 조용히 틀린 답을 낸다
# (2026-08-26 에 정확히 그 일이 있었다 — 검증만 `orig * 3` 으로 박혀 있어서,
#  doc_worker 가 만드는 IMAGE 행이 처음 생기자 매일 밤 거짓 실패를 내게 돼 있었다).
#
# ★ IMAGE 는 여기 없다. 사진은 doc_worker 가 수집하며 물건마다 있지도 않다
#   (사진이 없는 물건은 IMAGE 행이 아예 생기지 않는다). "auction 1행당 정확히 3행"이라는
#   이 파일의 불변식에 IMAGE 를 섞으면 그 불변식 자체가 성립하지 않는다.
MIGRATED_DOC_TYPE_COLUMNS = (
    ("SPEC", "has_spec_pdf"),
    ("STATUS", "has_status_doc"),
    ("APPRAISAL", "has_appraisal_pdf"),
)
MIGRATED_DOC_TYPES = tuple(dt for dt, _ in MIGRATED_DOC_TYPE_COLUMNS)


# 마지막 execute() 가 관측한 필드별 변경 건수. 테스트와 운영 점검이 읽는다
# (로그만 남기면 자동 검증이 불가능하다).
LAST_FIELD_CHANGES = {}

# 마지막 execute() 가 예약한 재수집 결과(`requeue_changed_documents()` 반환값).
# 위와 같은 이유로 노출한다 — 배치 로그 한 줄로는 자동 검증이 안 된다.
LAST_REQUEUE = {}

# 변경 기반 재수집을 끌 수 있는 스위치 (2026-08-18 Sprint 189).
# 기본은 켬이다 — 이 기능이 없으면 최초 1회 수집으로 끝나는 것이 곧 제품 결함이다.
# 사고 시 배치 한 줄로 되돌릴 수 있어야 하므로 환경변수로만 끈다(코드 수정 없이).
REFRESH_ON_CHANGE_ENV = "DOJOONPASS_REFRESH_ON_CHANGE"


def refresh_on_change_enabled() -> bool:
    """환경변수가 '0'/'false'/'no'면 끔. 그 외(미설정 포함)는 켬."""
    v = (os.environ.get(REFRESH_ON_CHANGE_ENV) or "").strip().lower()
    return v not in ("0", "false", "no", "off")

def extract_fail_count(status: str) -> int:
    if not status:
        return 0
    m = re.search(r"유찰\s*(\d+)회", status)
    if m:
        return int(m.group(1))
    if "유찰" in status:
        return 1
    return 0

def calc_bid_rate(appraisal: int, minimum: int) -> float:
    if appraisal > 0:
        return round(minimum / appraisal, 4)
    return 0.0

# 이 스크립트가 auction_item 에 **쓰는** 컬럼 중, 번호 마이그레이션이 나중에 추가한 것들.
# 없으면 아래 preflight 가 알아볼 수 있는 말로 막는다.
REQUIRED_ITEM_COLUMNS = {
    "building_area": "025_add_auction_item_area_columns.sql",
    "land_area": "025_add_auction_item_area_columns.sql",
}


# 접수일 보충 UPDATE (BUGS #285). **상수로 둔다** — 검사가 이 문장을 그대로
# 태워야 가드가 진짜 지켜지는지 알 수 있다. 문장을 검사 쪽에 베껴 쓰면 소스를
# 고쳐도 검사는 옛 문장을 태우므로 아무것도 안 지킨다(변이 M4 가 그렇게 살아남았다).
#
# `filed_date IS NULL` 은 **두 번째 겹**이다. 파이썬 쪽에서 이미 걸러 보내지만,
# 그 판단은 조회 시점의 스냅샷이라 다른 실행이 그 사이에 채웠을 수 있다 —
# 이 파일이 `INSERT OR IGNORE` 를 남겨 둔 것과 똑같은 이유다.
FILL_FILED_DATE_SQL = (
    "UPDATE auction_case SET filed_date = ?, updated_at = ?"
    " WHERE court_code = ? AND case_no = ? AND filed_date IS NULL"
)


def _raw_filed_date(row):
    """원시 `auction` 행에서 접수일을 꺼낸다. 없거나 빈 값이면 None.

    028 이전에 만들어진 DB 에는 컬럼 자체가 없을 수 있다 — 그때도 죽지 않는다
    (`sqlite3.Row` 는 없는 키에 IndexError 를 낸다).

    빈 문자열을 None 으로 바꾸는 것이 핵심이다. `''` 를 그대로 쓰면 "채웠다"가
    되어 **다시는 진짜 값으로 갱신되지 않는다** — 위 UPDATE 가 `IS NULL` 만
    보기 때문이다.
    """
    try:
        return (row["filed_date"] or None) if row["filed_date"] is not None else None
    except (IndexError, KeyError):
        return None


def _preflight(conn):
    """스키마가 이 스크립트보다 뒤처져 있으면 **알아볼 수 있는 말로** 막는다.

    왜 필요한가 (2026-08-27):
    `run_daily.bat` 은 3단계에서 마이그레이션을 먼저 돌리므로 운영 경로에서는 이 검사가
    걸리지 않는다. 걸리는 것은 **마이그레이션을 안 돌린 DB 에 이 스크립트만 따로 돌릴 때**다
    (개발/QA 장비에서 흔하고, 지금 이 저장소의 `auction.db` 가 정확히 그 상태다 —
    021~025 미적용).

    그때 나오던 메시지가 원인을 가렸다:

        (예전)  sqlite3.OperationalError: no such column: building_area
        (증분 비교 도입 후)  IndexError: No item with that key   <- 더 나쁘다

    둘 다 "무엇을 하면 되는지"를 말해 주지 않는다. 특히 뒤엣것은 `sqlite3.Row` 가
    없는 키에 내는 예외라 SQL 문제로 보이지도 않는다. 스키마 문제는 스키마 문제라고
    말하고, 실행할 명령까지 알려 준다.
    """
    have = {r[1] for r in conn.execute("PRAGMA table_info(auction_item)")}
    missing = sorted(c for c in REQUIRED_ITEM_COLUMNS if c not in have)
    if missing:
        raise SystemExit(
            "\n[중단] auction_item 에 필요한 컬럼이 없습니다: %s\n"
            "\n이 컬럼들은 아래 마이그레이션이 만듭니다:\n    %s\n"
            "\n먼저 실행하십시오:\n"
            "\n    python -m storage.migrations.run_migrations\n"
            "\n(`run_daily.bat` 은 이 스크립트보다 먼저 그것을 돌립니다. 지금 중단했으므로"
            "\n DB 는 전혀 변경되지 않았습니다.)\n"
            % (", ".join(missing),
               "\n    ".join(sorted({REQUIRED_ITEM_COLUMNS[c] for c in missing}))))


def execute():
    conn = get_connection()
    now = datetime.now().isoformat()
    try:
        _preflight(conn)
        rows = conn.execute("SELECT * FROM auction").fetchall()
        logger.info("원본 데이터 로드: %d건", len(rows))

        # 1. auction_case UPSERT
        # 식별키는 (court_code, case_no) 복합키다 — 법원마다 사건번호를 독립 채번하므로
        # case_no 단독으로 dedup하면 서로 다른 법원의 동일 사건번호가 한 row로 병합된다
        # (011_auction_case_court_code_unique.sql에서 해소한 Release Blocking 버그).
        logger.info("auction_case 마이그레이션 시작...")
        case_map = {}
        for row in rows:
            key = (row["court_code"], row["case_no"])
            if key not in case_map:
                case_map[key] = row

        # ── 이미 있는 사건은 **문장을 보내지 않는다** (2026-08-27) ────────────────
        #
        # 예전에는 유니크 사건 전부에 `INSERT OR IGNORE` 를 한 건씩 보냈다. 그런데 이 표는
        # 과거 사건까지 계속 누적되므로, 며칠만 지나면 그 문장은 **거의 전부 no-op** 이다.
        # 그래도 문장 하나당 UNIQUE 인덱스 탐색 + 파이썬<->C 왕복 비용은 그대로 든다.
        #
        # 실측(누적 50,000행 / 하루 1,900건이 바뀐 정상 상태, N=50,500 유니크 사건):
        #     INSERT OR IGNORE INTO auction_case   50,500회  346ms
        # 그중 실제로 행이 생기는 것은 그날 새로 등장한 사건 몇백 건뿐이다.
        #
        # 그래서 순서를 뒤집는다 — **먼저 있는 것을 읽고, 없는 것만 넣는다.**
        # 어차피 바로 아래에서 `case_id` 를 얻으려고 같은 조회를 하고 있었으므로
        # 조회가 늘지도 않는다(그 조회를 앞으로 옮긴 것뿐이다).
        # 결과는 `INSERT OR IGNORE` 와 동일하다: 있으면 그대로 두고, 없으면 만든다.
        case_keys = list(case_map.keys())
        case_id_by_key = {}
        filed_now = {}          # (court_code, case_no) -> 현재 auction_case.filed_date

        def _load_case_ids(keys):
            """(court_code, case_no) 목록의 id 를 `case_id_by_key` 에 채운다.

            ★★ 한 번에 다 넣지 않고 **나눈다** (2026-08-27, `docs/BUGS.md` #243).

              쌍 하나가 `?` 를 2개 쓰므로 SQLite 의 바인딩 변수 상한
              (`SQLITE_LIMIT_VARIABLE_NUMBER`, 이 환경 32,766)에 **유니크 사건
              16,384건째**에서 닿는다. 넘으면 느려지는 것이 아니라
              `OperationalError: too many SQL variables` 로 **실행이 죽는다.**

              실측(사본 DB, 합성 사건):  16,383건 정상 / 16,384건 파손
              파손 시 rollback 은 깨끗하지만 auction_case/item/document_status 가
              **전부 0건** — 그날 크롤이 통째로 버려진다.

              값을 SQL 텍스트로 밀어 넣는 우회(인젝션 위험)로 풀지 않는다 — **나누기만**
              한다. 나눠도 결과는 동일하다: 각 청크가 서로소인 키 집합을 조회한다.
              상한은 **이 커넥션에 직접 물어본다** — 상수로 박으면 SQLite 3.31 이하
              (기본값 999)에서 500건대부터 같은 사고가 난다.
            """
            for key_chunk in chunked_for_sql(keys, vars_per_item=2, conn=conn):
                placeholders = ",".join(["(?,?)"] * len(key_chunk))
                params = [v for pair in key_chunk for v in pair]
                for cc_row in conn.execute(
                    f"SELECT id, court_code, case_no, filed_date FROM auction_case "
                    f"WHERE (court_code, case_no) IN ({placeholders})",
                    params,
                ).fetchall():
                    key = (cc_row["court_code"], cc_row["case_no"])
                    case_id_by_key[key] = cc_row["id"]
                    # ★ 같은 조회에서 접수일도 들고 온다 (BUGS #285). 컬럼 하나를
                    #   더 읽는 것은 공짜지만, 따로 물으면 질의가 한 벌 늘어난다 —
                    #   이 파일이 #243/#247 에서 없앤 것과 같은 부류다.
                    filed_now[key] = cc_row["filed_date"]

        _load_case_ids(case_keys)
        missing_cases = [k for k in case_keys if k not in case_id_by_key]
        if missing_cases:
            # `INSERT OR IGNORE` 는 그대로 둔다 — 위 조회와 이 삽입 사이에 다른 실행이
            # 같은 사건을 넣었을 수 있다(운영에서 두 프로세스가 겹치는 것은 락으로 막지만,
            # 방어를 조회 시점 가정에 기대게 만들지 않는다).
            conn.executemany("""
                INSERT OR IGNORE INTO auction_case
                (case_no, court_code, court_name, case_type, filed_date, demand_deadline, created_at, updated_at)
                VALUES (?, ?, ?, NULL, ?, NULL, ?, ?)
            """, [(case_no, court_code, case_map[(court_code, case_no)]["court_name"],
                   # ★ 접수일을 처음부터 넣는다 (BUGS #285). 아래 보충 UPDATE 가
                   #   어차피 채우지만, 새 사건까지 UPDATE 로 미루면 **매일 새로
                   #   등장하는 사건 수만큼** 쓸데없는 문장이 하나씩 더 나간다.
                   _raw_filed_date(case_map[(court_code, case_no)]),
                   case_map[(court_code, case_no)]["created_at"] or now,
                   case_map[(court_code, case_no)]["updated_at"] or now)
                  for (court_code, case_no) in missing_cases])
            _load_case_ids(missing_cases)

        # ── 이미 있던 사건의 접수일을 **비어 있을 때만** 채운다 (BUGS #285) ──
        #
        # 접수일은 사건이 접수된 날이라 **한 번 정해지면 바뀌지 않는다.** 그래서
        # `COALESCE` 가 아니라 아예 `filed_date IS NULL` 인 행만 건드린다 -
        # 값이 이미 있으면 문장 자체를 만들지 않는다(#247 의 교훈: no-op 문장도
        # 누적 행수를 따라 비용을 낸다).
        #
        # 현재 값은 위 `_load_case_ids()` 가 같은 조회에서 이미 들고 왔다.
        filed_updates = []
        for key in case_keys:
            if filed_now.get(key):
                continue                      # 이미 있다 - 손대지 않는다
            got = _raw_filed_date(case_map[key])
            if got:
                filed_updates.append((got, now, key[0], key[1]))
        if filed_updates:
            conn.executemany(FILL_FILED_DATE_SQL, filed_updates)
            logger.info("auction_case 접수일 채움: %d건", len(filed_updates))

        logger.info("auction_case 완료: %d건 (신규 %d건, 기존 %d건)",
                    len(case_map), len(missing_cases), len(case_map) - len(missing_cases))

        # (이 조회는 위 auction_case 블록의 `_load_case_ids()` 로 옮겼다 — 2026-08-27.
        #  Sprint 129 가 §2/§3 의 row 단위 N+1 조회를 없애려고 여기 만든 것인데, 이제
        #  삽입 전에 먼저 읽어야 해서 앞으로 갔다. 상한 나누기 사유는 그 함수 docstring 참고.)

        # 2. auction_item UPSERT
        # Sprint: auction -> auction_item 최신화 동기화.
        # 기존 INSERT OR IGNORE는 최초 삽입 이후 재크롤링 값(가격/기일/상태/유찰횟수)이
        # 영원히 반영되지 않는 문제가 있어, 기존 row는 UPDATE로 갱신한다.
        # 단, 크롤링 값이 빈 문자열/0(파싱 실패 등)이면 기존 정상값을 지우지 않고 유지한다.
        #
        # 2026-08-07: 위 "Critical TODO"(court_code+case_no+item_no 식별키)의 남은 절반을 해소한다.
        # auction_case는 2026-08-06 Migration으로 (court_code, case_no) 복합키가 됐지만,
        # auction_item 조회/갱신은 여전히 `WHERE case_no=? AND item_no=?`로 **법원 구분이 없었다**.
        # 법원마다 사건번호를 독립 채번하므로 서로 다른 법원이 같은 (case_no, item_no)를 쓰면
        # 매일 크롤링이 한쪽 법원 데이터로 다른 법원 row를 덮어쓴다(docs/BUGS.md #14와 같은 계열).
        # 실측 결과 현재 그런 쌍은 0건이지만(사건번호 충돌 3건이 마침 item_no가 달랐다),
        # 사건번호 충돌 자체는 이미 존재하므로 언제든 터질 수 있는 잠재 결함이다.
        # 바로 위에서 (court_code, case_no)로 구한 case_id는 이미 법원까지 특정된 값이므로,
        # 식별키를 (case_id, item_no)로 바꾸면 스키마 변경 없이 법원 구분이 생긴다.
        logger.info("auction_item 마이그레이션 시작...")
        item_count = 0
        item_inserted = 0
        item_updated = 0
        item_unchanged = 0   # 값이 그대로라 UPDATE 를 보내지 않은 행
        field_changes = {}    # 필드명 -> 실제로 값이 바뀐 행 수
        changed_samples = []  # 로그에 남길 예시(최대 10건)
        changed_items = []    # 재수집 예약 대상(물건 키 + 바뀐 필드 목록)
        # (case_id, item_no) -> auction_item.id. §3 document_status 루프가 다시 JOIN으로
        # 같은 item_id를 조회하던 것을 대신한다(아래 §3 주석 참고).
        item_id_by_key = {}
        for row in rows:
            # 조회도 복합키 기준이어야 한다 — case_no만으로 찾으면 동일 사건번호를 쓰는
            # 다른 법원의 auction_case row를 잘못 연결하게 된다(위 UPSERT와 동일한 이유).
            # case_id는 위에서 이미 (court_code, case_no) 전체를 한 번에 읽어 둔 딕셔너리에서
            # 가져온다(개별 SELECT였던 것을 Sprint 129에서 없앴다) — case_map이 만들어질 때
            # 이 row의 (court_code, case_no)로 auction_case가 INSERT OR IGNORE됐으므로 항상 있다.
            case_id = case_id_by_key[(row["court_code"], row["case_no"])]

            existing = conn.execute(
                "SELECT * FROM auction_item WHERE case_id=? AND item_no=?",
                (case_id, row["item_no"])
            ).fetchone()

            if existing:
                court_name = row["court_name"] or existing["court_name"]
                property_type = row["property_type"] or existing["property_type"]
                sido = row["sido"] or existing["sido"]
                sigungu = row["sigungu"] or existing["sigungu"]
                dong = row["dong"] or existing["dong"]
                lot_number = row["lot_number"] or existing["lot_number"]
                full_address = row["full_address"] or existing["full_address"]
                appraisal_price = row["appraisal_price"] or existing["appraisal_price"]
                minimum_bid_price = row["minimum_bid_price"] or existing["minimum_bid_price"]
                auction_date = row["auction_date"] or existing["auction_date"]
                status = row["status"] or existing["status"]
                validation_status = row["validation_status"] or existing["validation_status"]
                crawl_date = row["crawl_date"] or existing["crawl_date"]
                fail_count = extract_fail_count(status)
                bid_rate = calc_bid_rate(appraisal_price, minimum_bid_price)

                # ── 변경 관측 (2026-08-17 Sprint 185) ─────────────────────────
                # UPDATE 자체는 그대로 두고, **무엇이 바뀌었는지만** 기록한다.
                #
                # 이 UPDATE는 값이 같아도 매번 실행된다. 그래서 `updated_at`이 전부 같은
                # 값이 되고(실측: 1,876행 100%가 2026-08-12), 물건 단위 변경 이력 테이블도
                # 없다. 결과적으로 "오늘 어떤 물건의 기일/최저가/상태가 바뀌었나"를 아무도
                # 답할 수 없었다. 법원 자료는 절차 진행에 따라 계속 바뀌므로 그 답이 곧
                # 제품 가치다(유찰 -> 재매각 시 기일과 최저가가 함께 움직인다).
                #
                # 스키마도 UPDATE 조건도 건드리지 않는다 — 이미 손에 있는 `existing`과
                # 새 값을 비교해 집계만 한다. 관측이 먼저 있어야 재수집/알림 정책을
                # 숫자로 정할 수 있다(docs/roadmap.md 재수집 정책 항목).
                changed_fields = []
                for _f, _old, _new in (
                    ("auction_date", existing["auction_date"], auction_date),
                    ("minimum_bid_price", existing["minimum_bid_price"], minimum_bid_price),
                    ("status", existing["status"], status),
                    ("appraisal_price", existing["appraisal_price"], appraisal_price),
                ):
                    if (_old or "") != (_new or ""):
                        changed_fields.append(_f)
                        field_changes[_f] = field_changes.get(_f, 0) + 1
                        if len(changed_samples) < 10:
                            changed_samples.append(
                                "%s-%s %s: %s -> %s"
                                % (row["case_no"], row["item_no"], _f, _old, _new))

                # ── 관측에서 행동으로 (2026-08-18 Sprint 189) ─────────────────
                # Sprint 185는 여기서 **세기만** 했다. 그 숫자만으로는 화면이 최신이 되지
                # 않는다 — 물건 기본정보(기일/최저가/상태/감정가)는 바로 아래 UPDATE로
                # 갱신되지만, 그 변경에 딸린 **문서와 사진은 최초 수집분 그대로** 남는다.
                # 어느 물건이 바뀌었는지를 여기서 모아 두었다가 커밋 뒤에 큐를 되돌린다.
                if changed_fields:
                    changed_items.append({
                        "court_code": row["court_code"],
                        "case_no": row["case_no"],
                        "item_no": row["item_no"],
                        "fields": changed_fields,
                    })

                # 면적은 `full_address` 에서 파생된다 — 주소가 갱신되면 함께 다시 뽑는다
                # (2026-08-26). 못 뽑으면 None 이 들어가 컬럼이 NULL 로 남는다.
                _areas = extract_areas(full_address or "")

                # ── 값이 그대로면 UPDATE 를 보내지 않는다 (2026-08-27) ─────────
                #
                # 이 함수는 `SELECT * FROM auction` 으로 **누적 전체**를 읽어 매일 전부
                # UPDATE 했다. 하루에 새로 들어오는 것은 1,900건 안팎인데, 비용은
                # 그날 수집량이 아니라 **누적 행수**를 따라간다. 실측(하루치 실행 1회):
                #
                #     누적       upsert   enqueue  migrate   합계
                #      2,000      46ms      89ms    208ms     0.34초
                #      5,000      81ms     148ms    508ms     0.74초
                #     10,000     246ms     652ms  3,902ms     4.80초
                #     25,000   1,377ms   1,653ms 10,322ms    13.35초
                #     50,000   2,478ms   2,718ms 15,942ms    21.14초
                #
                # 25배 데이터에 62배 시간이다. 비용이 어디로 가는지도 쟀다 —
                # N=25,000 프로파일에서 `INSERT/UPDATE auction_item` 한 문장이
                # 전체의 49.8%(25,000회 1,625ms, 건당 65µs)였다. 같은 실행의
                # `document_status` INSERT 는 건당 9.8µs 다. 차이는 **인덱스 개수**다
                # (auction_item 15개 vs document_status 2개, 65/9.8 = 6.6배로 거의 정확히
                # 비례한다). 즉 진짜 병목은 쿼리 횟수가 아니라 **인덱스 쓰기 증폭**이고,
                # 행 단위 SELECT 는 전체의 2.5%에 불과했다(그쪽을 고쳐도 소용없다).
                #
                # 그러면 답은 "더 빨리 쓴다"가 아니라 **안 바뀐 행은 쓰지 않는다**이다.
                # 누적분의 대부분은 오늘 크롤 대상이 아니라 `auction` 쪽 값이 그대로이므로,
                # 지금 쓰려는 값이 `existing` 과 전부 같으면 UPDATE 를 건너뛴다.
                #
                # ★ 비교는 **쓰는 값 전부**로 한다. 위 `changed_fields` 4개(기일/최저가/
                #   상태/감정가)만 보면 안 된다 — 주소 정정이나 면적 백필처럼 그 4개 밖에서
                #   일어나는 갱신을 놓치고 조용히 반영되지 않는다.
                #
                # ★ `updated_at` 은 비교에서 뺀다. 매 실행 `now` 라 넣으면 항상 달라져
                #   건너뛸 수 있는 행이 하나도 없어진다. 대신 의미가 **좋아진다** —
                #   지금까지는 전 행이 마지막 실행 시각이라 아무 정보가 없었고
                #   (실측: 1,876행 100%가 같은 값), 이제 "이 행이 마지막으로 실제
                #   변한 시각"이 된다. 제품 코드에 `auction_item.updated_at` 을 읽는 곳은
                #   없다(전수 확인). 수집 신선도는 `audit_schedule_health.py` 가
                #   `MAX(auction_item.crawl_date)` 로 보는데, 오늘 크롤된 행은 crawl_date 가
                #   달라져 그대로 UPDATE 되므로 그 판정은 바뀌지 않는다.
                _new = (court_name, property_type, sido, sigungu, dong,
                        lot_number, full_address, appraisal_price,
                        minimum_bid_price, auction_date, status,
                        fail_count, bid_rate, validation_status, crawl_date,
                        _areas["building_area"], _areas["land_area"])
                _old = (existing["court_name"], existing["property_type"],
                        existing["sido"], existing["sigungu"], existing["dong"],
                        existing["lot_number"], existing["full_address"],
                        existing["appraisal_price"], existing["minimum_bid_price"],
                        existing["auction_date"], existing["status"],
                        existing["fail_count"], existing["bid_rate"],
                        existing["validation_status"], existing["crawl_date"],
                        existing["building_area"], existing["land_area"])

                if _new == _old:
                    item_unchanged += 1
                else:
                    conn.execute("""
                        UPDATE auction_item SET
                            court_name=?, property_type=?, sido=?, sigungu=?, dong=?,
                            lot_number=?, full_address=?, appraisal_price=?,
                            minimum_bid_price=?, auction_date=?, status=?,
                            fail_count=?, bid_rate=?, validation_status=?,
                            crawl_date=?, updated_at=?,
                            building_area=?, land_area=?
                        WHERE case_id=? AND item_no=?
                    """, (
                        court_name, property_type, sido, sigungu, dong,
                        lot_number, full_address, appraisal_price,
                        minimum_bid_price, auction_date, status,
                        fail_count, bid_rate, validation_status,
                        crawl_date, now,
                        _areas["building_area"], _areas["land_area"],
                        case_id, row["item_no"],
                    ))
                    item_updated += 1
                item_id_by_key[(case_id, row["item_no"])] = existing["id"]
            else:
                _areas = extract_areas(row["full_address"] or "")
                cur = conn.execute("""
                    INSERT INTO auction_item
                    (case_id, case_no, item_no, court_name, property_type,
                     sido, sigungu, dong, lot_number, full_address,
                     appraisal_price, minimum_bid_price, auction_date,
                     status, fail_count, bid_rate, validation_status,
                     crawl_date, created_at, updated_at,
                     building_area, land_area)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    case_id,
                    row["case_no"], row["item_no"], row["court_name"],
                    row["property_type"], row["sido"], row["sigungu"],
                    row["dong"], row["lot_number"], row["full_address"],
                    row["appraisal_price"], row["minimum_bid_price"],
                    row["auction_date"], row["status"],
                    extract_fail_count(row["status"]),
                    calc_bid_rate(row["appraisal_price"], row["minimum_bid_price"]),
                    row["validation_status"],
                    row["crawl_date"],
                    row["created_at"] or now,
                    now,
                    _areas["building_area"], _areas["land_area"],
                ))
                item_inserted += 1
                item_id_by_key[(case_id, row["item_no"])] = cur.lastrowid
            item_count += 1

        # 건너뛴 건수를 **반드시 함께** 남긴다. 이 값이 0에 가까우면 위 최적화가
        # 무력화된 것이고(예: 매일 달라지는 필드가 새로 UPDATE 목록에 들어옴),
        # 그때 조용히 느려지는 대신 로그에서 먼저 보이게 하려는 것이다.
        logger.info("auction_item 완료: %d건 (신규 %d건, 갱신 %d건, 변화없어 건너뜀 %d건)",
                    item_count, item_inserted, item_updated, item_unchanged)

        # 3. document_status 마이그레이션
        logger.info("document_status 마이그레이션 시작...")

        # ── 이미 있는 (item_id, doc_type) 은 **문장을 보내지 않는다** (2026-08-27) ──
        #
        # 이 루프는 auction 한 행마다 `INSERT OR IGNORE` 를 3번 보냈다. `document_status`
        # 는 물건이 처음 등장할 때 한 번 만들어지고 그 뒤로는 계속 남으므로, 정상 상태에서
        # 이 문장은 **거의 전부 no-op** 이다. 그런데도 매번 UNIQUE 인덱스 탐색과
        # 파이썬<->C 왕복 비용을 낸다. 이 파일에서 **가장 많이 실행되는 문장**이었다.
        #
        # 실측(누적 50,000행, 하루 1,900건 변경의 정상 상태):
        #     INSERT OR IGNORE INTO document_status   151,500회  1,116ms  (SQL 시간의 18.8%)
        #     실제로 행이 생기는 것                     1,500건 (그날 신규 물건 500 x 3종)
        #
        # cProfile 로 보면 이 파일 전체(4.87초)에서 `sqlite3.Connection.execute` 가
        # 2.54초(52%)였고 호출이 254,892회였다 — 즉 남은 병목은 쿼리 하나의 무게가 아니라
        # **문장 개수 그 자체**다. 그래서 "빨리 보내기"가 아니라 **안 보내기**로 푼다.
        #
        # 있는 것을 한 번에 읽어 집합으로 들고, 없는 것만 `executemany` 로 넣는다.
        # 결과는 `INSERT OR IGNORE` 와 동일하다 — 있으면 그대로 두고(상태도 그대로:
        # OR IGNORE 는 원래 갱신하지 않았다) 없으면 만든다.
        #
        # doc_worker 가 만드는 IMAGE 행도 이 집합에 섞여 들어오지만 무해하다 —
        # 아래 루프는 `MIGRATED_DOC_TYPE_COLUMNS` 의 3종만 조회한다.
        existing_ds = set()
        for _ds in conn.execute("SELECT item_id, doc_type FROM document_status"):
            existing_ds.add((_ds["item_id"], _ds["doc_type"]))

        ds_pending = []
        ds_count = 0
        for row in rows:
            # ★ 조회에 법원이 들어가야 한다 (2026-08-14).
            #
            # 위 auction_item UPSERT는 2026-08-07에 `(case_id, item_no)` 로 고쳤는데
            # **이 조회만 옛 형태(`case_no` + `item_no`)로 남아 있었다.** 같은 수정의
            # 나머지 절반이다.
            #
            # 법원마다 사건번호를 독립 채번하므로 서로 다른 법원이 같은 (case_no, item_no)
            # 를 쓰면 이 조회는 **둘 중 아무 행이나** 돌려준다. 그러면 두 물건의 문서
            # 상태가 한 item_id 로 몰리고, `INSERT OR IGNORE` 라 나중 것이 조용히 버려진다.
            #
            # 사본 재현(2026-08-14): 부산 물건2(수집완료) + 수원 물건2(미수집) 를 만들자
            #
            #     부산 item : document_status 행이 **아예 없음**  <- 수집한 문서를 못 본다
            #     수원 item : COLLECTING (자기 값)
            #     자체 검증 : document_status 5628 != 5631
            #
            # 실 DB에는 법원이 다른 같은 사건번호가 **3개** 있다(2024타경34089 / 2024타경3700
            # / 2024타경4973). 지금은 물건번호가 마침 달라 무사하지만, 한쪽에 같은 물건번호가
            # 생기는 순간 터진다 — 진행 중인 사건들이라 언제든 생길 수 있다.
            #
            # 2026-08-15 Sprint 129: 위 §2 루프가 이미 같은 신원(법원+사건→case_id,
            # case_id+item_no→item_id)을 방금 확정해 `item_id_by_key`에 담아 뒀다 — 바로
            # 아래에서 JOIN으로 다시 물어보던 조회를 그 결과 재사용으로 바꾼다(row 수만큼
            # 반복되는 조회였다). 식별 로직 자체는 그대로다: (court_code, case_no)로 case_id를
            # 먼저 구하고, (case_id, item_no)로 item을 특정한다 — `storage/database.py:
            # _document_status_item_id()`와 맞춘 원래 조회의 두 단계와 동일한 키를 쓴다.
            case_id = case_id_by_key.get((row["court_code"], row["case_no"]))
            item_id = item_id_by_key.get((case_id, row["item_no"])) if case_id is not None else None
            if item_id is None:
                continue

            for doc_type, col in MIGRATED_DOC_TYPE_COLUMNS:
                ds_count += 1
                if (item_id, doc_type) in existing_ds:
                    continue
                status = "READY" if row[col] == 1 else "COLLECTING"
                ds_pending.append((item_id, doc_type, status, now))
                # 같은 실행 안에서 같은 키가 두 번 나오는 것도 막는다
                # (auction 의 UNIQUE 제약상 있어서는 안 되지만, 방어를 그 가정에 기대지 않는다)
                existing_ds.add((item_id, doc_type))

        if ds_pending:
            # `INSERT OR IGNORE` 를 그대로 둔다 — 위 조회와 이 삽입 사이에 다른 실행이
            # 같은 행을 넣었을 수 있다(auction_case 쪽과 같은 이유).
            conn.executemany("""
                INSERT OR IGNORE INTO document_status
                (item_id, doc_type, status, updated_at)
                VALUES (?, ?, ?, ?)
            """, ds_pending)

        # 대상 건수와 **실제로 넣은 건수**를 함께 남긴다. 둘째 값이 매일 크게 나오면
        # document_status 가 어딘가에서 지워지고 있다는 뜻이라 그 자체가 신호다.
        logger.info("document_status 완료: 대상 %d건 (신규 %d건, 기존 %d건)",
                    ds_count, len(ds_pending), ds_count - len(ds_pending))

        conn.commit()
        logger.info("마이그레이션 커밋 완료")

        # 건수 검증
        print("")
        print("=== 마이그레이션 결과 검증 ===")
        ac = conn.execute("SELECT COUNT(*) FROM auction_case").fetchone()[0]
        ai = conn.execute("SELECT COUNT(*) FROM auction_item").fetchone()[0]
        # ★ **문서 3종만** 센다 (2026-08-26).
        #
        #   이 검증의 불변식은 *"`auction` 1행마다 document_status 3행(SPEC/STATUS/
        #   APPRAISAL)이 생긴다"* 이고, 그 3행을 만드는 것이 바로 아래 §3 루프다.
        #
        #   그런데 `document_status` 에는 **doc_worker 가 만드는 `IMAGE` 행도 들어온다.**
        #   사진 수집은 migrate_execute 가 하는 일이 아니고 물건마다 있지도 않다
        #   (사진이 없는 물건은 IMAGE 행이 아예 안 생긴다). 그것까지 세면
        #   `ds == orig * 3` 이 **구조적으로 성립할 수 없다.**
        #
        #   2026-08-26 에 실제로 그렇게 됐다 — `DojoonPass-DocWorker` 를 등록하고 처음
        #   돌리자 IMAGE 17행이 생겼고, 이 검증이 `7697 != 7680` 로 붉어졌다.
        #   차이는 정확히 그 17이다. 데이터는 멀쩡한데 검증만 틀린 것이다.
        #
        #   그리고 이 판정은 **exit 1 로 이어진다**(바로 아래 problems 처리).
        #   즉 고치지 않으면 오늘 밤 03:00 부터 `run_daily.bat` 이 매일 `[FAILED]` 를
        #   남긴다 — 이 파일이 그토록 경계해 온 "거짓 실패"가 반대 방향으로 재발한다.
        #   거짓 실패가 쌓이면 진짜 실패가 그 속에 묻힌다.
        #
        #   doc_type 목록을 여기 박아 두는 대신 §3 이 넣는 값과 같은 상수를 쓴다.
        ds = conn.execute(
            "SELECT COUNT(*) FROM document_status WHERE doc_type IN (%s)"
            % ",".join("?" * len(MIGRATED_DOC_TYPES)),
            MIGRATED_DOC_TYPES,
        ).fetchone()[0]
        orig = conn.execute("SELECT COUNT(*) FROM auction").fetchone()[0]

        print(f"  auction 원본        : {orig}건")
        print(f"  auction_case        : {ac}건")
        print(f"  auction_item        : {ai}건")
        print(f"  document_status     : {ds}건 (문서 3종만. IMAGE 제외)")

        # 이모지(✅/❌)를 쓰지 않는다 — run_daily.bat이 stdout을 로그 파일로 리다이렉트하면
        # 이 환경의 파이썬이 cp949로 인코딩하는데 이모지가 cp949에 없어 UnicodeEncodeError로
        # 죽는다. 커밋은 이미 끝난 뒤라 데이터는 정상이지만 스크립트가 exit 1로 종료되어
        # 매일 배치가 실패로 보고됐다(logs/migrate_execute.log에 11회 발생 실측).
        # ★ [FAIL]을 찍고도 exit 0으로 끝나면 안 된다 (2026-08-14).
        #
        # 예전에는 이 두 검증이 **출력만** 했다. 그래서 `run_daily.bat`은
        # `if errorlevel 1` 에 걸리지 않고 로그 끝에 `[SUCCESS]` 를 남겼다 —
        # **자기 검증이 실패했다고 적어 둔 그 로그 파일에** 성공 마커가 함께 찍혔다.
        #
        # 사본 재현(2026-08-14): 법원이 다른 같은 (사건,물건)을 만들자
        # `[FAIL] document_status 불일치: 5628 != 5631` 이 찍혔는데 **종료코드는 0**이었다.
        # 문서 상태 3건이 유실됐는데 스케줄러에는 성공으로 보고된다.
        #
        # 이 저장소가 Sprint 13/54/99에서 `.bat` 계층에 대해 없앤 "실패 은폐"와 같은 모양이고,
        # 이번에는 파이썬 쪽에 남아 있었다.
        #
        # 판정 대상은 **결정적인 건수 검증 두 개뿐**이다. 예전에 이모지 인코딩 때문에
        # 데이터는 정상인데 exit 1로 끝나 매일 실패로 보고된 일이 있었다(위 주석) —
        # 그런 거짓 실패가 다시 생기지 않게 판정 근거를 좁게 유지한다.
        problems = []

        if ai == orig:
            print("  [OK] auction_item 건수 일치")
        else:
            problems.append(f"auction_item 불일치: {ai} != {orig}")
            print(f"  [FAIL] {problems[-1]}")

        if ds == orig * 3:
            print("  [OK] document_status 건수 일치")
        else:
            problems.append(f"document_status 불일치: {ds} != {orig * 3}")
            print(f"  [FAIL] {problems[-1]}")

        global LAST_FIELD_CHANGES, LAST_REQUEUE
        LAST_FIELD_CHANGES = dict(field_changes)

        # ── 변경 기반 재수집 예약 ───────────────────────────────────────────
        # **커밋 뒤에** 부른다. 이 함수는 자기 커넥션을 따로 열어 쓰므로(SQLite는
        # 같은 파일에 대한 두 번째 쓰기 커넥션이 미커밋 트랜잭션을 볼 수 없다),
        # 커밋 전에 부르면 방금 갱신한 값을 못 보거나 락 대기에 걸린다.
        #
        # 실패해도 마이그레이션 자체를 실패로 만들지 않는다 — 물건 기본정보 갱신은
        # 이미 커밋됐고, 재수집 예약은 그 위에 얹는 **다음 주기용 준비 작업**이다.
        # 여기서 예외를 올리면 이미 성공한 매일 크롤링이 exit 1로 보고된다.
        LAST_REQUEUE = {}
        if not changed_items:
            logger.info("변경된 물건이 없어 재수집 예약을 건너뛴다")
        elif not refresh_on_change_enabled():
            logger.warning("변경 기반 재수집이 %s로 꺼져 있다 - 물건 %d건의 문서/사진은 "
                           "옛 수집분 그대로 남는다", REFRESH_ON_CHANGE_ENV, len(changed_items))
        else:
            try:
                LAST_REQUEUE = requeue_changed_documents(changed_items)
            except Exception as exc:  # noqa: BLE001
                logger.error("재수집 예약 실패(물건 기본정보 갱신은 이미 커밋됨): %s", str(exc))

        # 변경 관측 결과. 0건이면 "바뀐 것이 없다"가 사실이고, 그것도 정보다.
        print("")
        print("=== 이번 실행에서 실제로 값이 바뀐 항목 ===")
        if field_changes:
            for _f in sorted(field_changes):
                print("  %-20s %d건" % (_f, field_changes[_f]))
            for _s in changed_samples:
                print("     %s" % _s)
            logger.info("auction_item 변경 관측: %s",
                        ", ".join("%s %d건" % (k, field_changes[k])
                                  for k in sorted(field_changes)))
        else:
            print("  없음 (기일/최저가/상태/감정가 모두 이전과 동일)")

        print("")
        print("=== 변경 기반 재수집 예약 ===")
        if LAST_REQUEUE:
            print("  대상 물건        %d건" % LAST_REQUEUE.get("items", 0))
            print("  재수집 예약      %d행 (done -> refresh)" % LAST_REQUEUE.get("refreshed", 0))
            print("  기일부활         %d행 (SKIPPED_EXPIRED -> pending)"
                  % LAST_REQUEUE.get("revived_expired", 0))
            if LAST_REQUEUE.get("skipped_over_cap"):
                print("  상한으로 미룸    %d건 (다음 실행에서 다시 후보)"
                      % LAST_REQUEUE["skipped_over_cap"])
        else:
            print("  없음")

        print("")
        print("=== 샘플 확인 ===")
        sample = conn.execute("""
            SELECT ai.case_no, ai.item_no, ai.fail_count, ai.bid_rate,
                   ac.court_name
            FROM auction_item ai
            JOIN auction_case ac ON ai.case_id = ac.id
            LIMIT 3
        """).fetchall()
        for s in sample:
            print(f"  {s['case_no']} | {s['item_no']} | fail={s['fail_count']} | rate={s['bid_rate']} | {s['court_name']}")

        if problems:
            # 로그에도 남긴다 — stdout은 배치가 파일로 리다이렉트하지만, 사유가
            # 한 줄로 모여 있어야 사고 때 찾기 쉽다.
            logger.error("마이그레이션 검증 실패 %d건: %s", len(problems), " / ".join(problems))
        return not problems

    except Exception as e:
        conn.rollback()
        logger.error("마이그레이션 실패: %s", str(e))
        raise
    finally:
        conn.close()
        
if __name__ == "__main__":
    try:
        # 검증이 실패하면 exit 1 — run_daily.bat의 `if errorlevel 1`이 이것을 보고
        # 로그에 [FAILED]를 남긴다. 예전에는 [FAIL]을 찍고도 0으로 끝나 [SUCCESS]가 찍혔다.
        sys.exit(0 if execute() else 1)
    except Exception as e:
        print("FATAL:", str(e))
        sys.exit(1)
