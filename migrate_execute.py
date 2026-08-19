import sys, os, re
sys.path.insert(0, os.getcwd())
from storage.database import get_connection, requeue_changed_documents
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

def execute():
    conn = get_connection()
    now = datetime.now().isoformat()
    try:
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

        for (court_code, case_no), row in case_map.items():
            conn.execute("""
                INSERT OR IGNORE INTO auction_case
                (case_no, court_code, court_name, case_type, filed_date, demand_deadline, created_at, updated_at)
                VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?)
            """, (case_no, court_code, row["court_name"],
                  row["created_at"] or now, row["updated_at"] or now))

        logger.info("auction_case 완료: %d건", len(case_map))

        # 2026-08-15 Sprint 129: (court_code, case_no) -> case_id를 한 번에 메모리로 읽어 온다.
        # 아래 두 루프(§2 auction_item, §3 document_status)가 원래 각자 row마다
        # `SELECT ... WHERE court_code=? AND case_no=?`를 따로 실행했다(N+1) — 위에서 이미
        # case_map으로 (court_code, case_no) 단위 유니크 집합을 구해 뒀는데, 그 뒤 row 단위로
        # 다시 조회하고 있었다. 인덱스가 있어 각 조회 자체는 빠르지만(현재 실측 2,156건에서
        # 체감 지연 없음), row 수만큼 배로 늘어나는 구조라 크롤 데이터가 늘수록 그대로
        # 커진다. `auction_case`는 과거 사건까지 계속 누적되는 테이블이라(오늘 기준
        # 1,574건 = case_map과 우연히 같지만 항상 같다는 보장은 없다) 전체를 긁는 대신,
        # SQLite의 row-value IN(3.15+, 이 환경 3.50)으로 지금 필요한 키만 한 번에 읽는다 —
        # 결과는 기존 개별 조회와 동일하다(같은 UNIQUE(court_code, case_no) 제약을 그대로 사용).
        case_keys = list(case_map.keys())
        case_id_by_key = {}
        if case_keys:
            placeholders = ",".join(["(?,?)"] * len(case_keys))
            params = [v for pair in case_keys for v in pair]
            for cc_row in conn.execute(
                f"SELECT id, court_code, case_no FROM auction_case "
                f"WHERE (court_code, case_no) IN ({placeholders})",
                params,
            ).fetchall():
                case_id_by_key[(cc_row["court_code"], cc_row["case_no"])] = cc_row["id"]

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

                conn.execute("""
                    UPDATE auction_item SET
                        court_name=?, property_type=?, sido=?, sigungu=?, dong=?,
                        lot_number=?, full_address=?, appraisal_price=?,
                        minimum_bid_price=?, auction_date=?, status=?,
                        fail_count=?, bid_rate=?, validation_status=?,
                        crawl_date=?, updated_at=?
                    WHERE case_id=? AND item_no=?
                """, (
                    court_name, property_type, sido, sigungu, dong,
                    lot_number, full_address, appraisal_price,
                    minimum_bid_price, auction_date, status,
                    fail_count, bid_rate, validation_status,
                    crawl_date, now,
                    case_id, row["item_no"],
                ))
                item_updated += 1
                item_id_by_key[(case_id, row["item_no"])] = existing["id"]
            else:
                cur = conn.execute("""
                    INSERT INTO auction_item
                    (case_id, case_no, item_no, court_name, property_type,
                     sido, sigungu, dong, lot_number, full_address,
                     appraisal_price, minimum_bid_price, auction_date,
                     status, fail_count, bid_rate, validation_status,
                     crawl_date, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                ))
                item_inserted += 1
                item_id_by_key[(case_id, row["item_no"])] = cur.lastrowid
            item_count += 1

        logger.info("auction_item 완료: %d건 (신규 %d건, 갱신 %d건)",
                    item_count, item_inserted, item_updated)

        # 3. document_status 마이그레이션
        logger.info("document_status 마이그레이션 시작...")
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

            for doc_type, col in [
                ("SPEC", "has_spec_pdf"),
                ("STATUS", "has_status_doc"),
                ("APPRAISAL", "has_appraisal_pdf"),
            ]:
                status = "READY" if row[col] == 1 else "COLLECTING"
                conn.execute("""
                    INSERT OR IGNORE INTO document_status
                    (item_id, doc_type, status, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (item_id, doc_type, status, now))
                ds_count += 1

        logger.info("document_status 완료: %d건", ds_count)

        conn.commit()
        logger.info("마이그레이션 커밋 완료")

        # 건수 검증
        print("")
        print("=== 마이그레이션 결과 검증 ===")
        ac = conn.execute("SELECT COUNT(*) FROM auction_case").fetchone()[0]
        ai = conn.execute("SELECT COUNT(*) FROM auction_item").fetchone()[0]
        ds = conn.execute("SELECT COUNT(*) FROM document_status").fetchone()[0]
        orig = conn.execute("SELECT COUNT(*) FROM auction").fetchone()[0]

        print(f"  auction 원본        : {orig}건")
        print(f"  auction_case        : {ac}건")
        print(f"  auction_item        : {ai}건")
        print(f"  document_status     : {ds}건")

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
