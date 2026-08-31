import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from storage.database import get_connection
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# document_status.status 값 (2026-08-31 정정 — NO_IMAGE 가 빠져 있었다)
#   실제로 쓰이는 값   COLLECTING / READY / NO_IMAGE / FAILED
#   자리만 잡아 둔 값   OCR / PARSING / ANALYZING   (쓰는 코드 0곳, DB 행 0건)
# 정의는 `api/constants.py:DocumentStatus` 가 기준이다. NO_IMAGE 는 "법원이 사진을
# 제공하지 않는다"는 **확인된 답**이지 실패가 아니다(재시도해도 같다).

# auction_item.property_type 의 실제 어휘 (2026-08-31 정정 — 아래 서술은 실측이다)
#
# ★ 이 자리에는 원래 "APARTMENT / OFFICETEL / LAND / FACTORY / COMMERCIAL /
#   MULTI_FAMILY" 라는 ENUM 코드 규칙이 적혀 있었다. **그 값은 코드에도 DB 에도
#   존재한 적이 없다** — 2026-08-31 auction.db 전수(1,876행)에서 사용 행 0건이고,
#   저장소 어느 소스도 그 문자열을 만들지 않는다(`grep -r APARTMENT` = 이 주석뿐).
#   `docs/backend.md` 주의사항에도 같은 문장이 복사돼 있었고 함께 정정했다.
#
#   실제로는 **법원 표기 그대로의 한국어 자유 문자열**이며, 콤마로 이어 붙은
#   복합값이 있다(한 물건이 여러 종류를 겸한다). 2026-08-31 실측 18종
#   [VOCAB-TABLE]  <- 이 표는 test_property_type_vocabulary.py 가 DB 와 대조한다:
#
#       기타 259 / 다세대 246 / 상가,오피스텔,근린시설 205 / 아파트 201 / 전답 188
#       근린시설 164 / 연립주택,다세대,빌라 133 / 임야 123 / 오피스텔 102
#       대지,임야,전답 56 / 대지 47 / 단독주택,다가구주택 43 / 단독주택 42
#       다가구주택 33 / 상가 18 / 자동차,중기 9 / 자동차 4 / 연립주택 3
#
#   검색은 이 값을 `LIKE %패턴%` 으로 맞추고, UI 어휘(69종)와의 차이는
#   `api/v1/search.py:PROPERTY_TYPE_ALIASES` 가 잇는다(`docs/BUGS.md` #33).
#   어휘를 어느 쪽으로 통일할지는 제품 판단이라 여기서 정하지 않는다 —
#   여기서는 **없는 규칙을 있다고 적어 두지 않는 것**까지만 한다.
#   회귀: `test_property_type_vocabulary.py` 의 어휘 계약 검사.

def migrate():
    conn = get_connection()
    try:
        logger.info("v4.1 스키마 마이그레이션 시작...")

        # 1. auction_case
        conn.execute("""
        CREATE TABLE IF NOT EXISTS auction_case (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_no TEXT UNIQUE NOT NULL,
            court_name TEXT,
            case_type TEXT,
            filed_date TEXT,
            demand_deadline TEXT,
            created_at TEXT,
            updated_at TEXT
        )""")
        logger.info("auction_case 생성 완료")

        # 2. auction_item
        conn.execute("""
        CREATE TABLE IF NOT EXISTS auction_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER REFERENCES auction_case(id),
            case_no TEXT NOT NULL,
            item_no TEXT,
            court_name TEXT,
            property_type TEXT,
            sido TEXT,
            sigungu TEXT,
            dong TEXT,
            lot_number TEXT,
            full_address TEXT,
            appraisal_price INTEGER DEFAULT 0,
            minimum_bid_price INTEGER DEFAULT 0,
            auction_date TEXT,
            status TEXT,
            fail_count INTEGER DEFAULT 0,
            bid_rate REAL DEFAULT 0,
            validation_status TEXT,
            crawl_date TEXT,
            created_at TEXT,
            updated_at TEXT,
            -- 식별키는 case_id 기반이다. case_id가 가리키는 auction_case는 이미
            -- UNIQUE(court_code, case_no)라 법원이 특정되어 있으므로, (case_id, item_no)는
            -- "법원+사건번호+물건번호"와 동치이면서 같은 정보를 중복 저장하지 않는다.
            -- 예전 UNIQUE(case_no, item_no)는 법원 구분이 없어 서로 다른 법원의 물건을
            -- 한 행으로 취급했다(docs/BUGS.md #18, 기존 DB는 마이그레이션 013으로 이관 완료).
            UNIQUE(case_id, item_no)
        )""")
        logger.info("auction_item 생성 완료")

        # 3. document_status
        # status: 값 목록은 이 파일 상단 주석과 `api/constants.py:DocumentStatus` 참고
        conn.execute("""
        CREATE TABLE IF NOT EXISTS document_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES auction_item(id),
            doc_type TEXT NOT NULL,
            status TEXT DEFAULT 'COLLECTING',
            updated_at TEXT,
            UNIQUE(item_id, doc_type)
        )""")
        logger.info("document_status 생성 완료")

        # 4. doc_raw (원본 파일 보관)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES auction_item(id),
            doc_type TEXT NOT NULL,
            storage_path TEXT,
            file_hash TEXT,
            file_size INTEGER,
            doc_version INTEGER DEFAULT 1,
            page_count INTEGER,
            crawl_date TEXT,
            created_at TEXT,
            UNIQUE(item_id, doc_type, doc_version)
        )""")
        logger.info("doc_raw 생성 완료")

        # 5. parsed_document (raw_text 없음 - doc_raw에서 원본 관리)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS parsed_document (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_raw_id INTEGER NOT NULL REFERENCES doc_raw(id),
            item_id INTEGER NOT NULL REFERENCES auction_item(id),
            doc_type TEXT NOT NULL,
            parsed_json TEXT,
            parser_version TEXT,
            created_at TEXT,
            UNIQUE(doc_raw_id)
        )""")
        logger.info("parsed_document 생성 완료")

        # 6. tenant_rights (원본 데이터만, 분석 결과 없음)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tenant_rights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES auction_item(id),
            tenant_name TEXT,
            occupied_area TEXT,
            deposit INTEGER DEFAULT 0,
            monthly_rent INTEGER DEFAULT 0,
            move_in_date TEXT,
            fixed_date TEXT,
            demand_date TEXT,
            has_demand INTEGER DEFAULT 0,
            source TEXT,
            created_at TEXT,
            UNIQUE(item_id, tenant_name, move_in_date)
        )""")
        logger.info("tenant_rights 생성 완료")

        # 7. rights_summary
        conn.execute("""
        CREATE TABLE IF NOT EXISTS rights_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL UNIQUE REFERENCES auction_item(id),
            priority_right TEXT,
            priority_date TEXT,
            total_tenant_count INTEGER DEFAULT 0,
            dangerous_tenant_count INTEGER DEFAULT 0,
            total_deposit INTEGER DEFAULT 0,
            estimated_inheritance INTEGER DEFAULT 0,
            lien_exists INTEGER DEFAULT 0,
            superficies_exists INTEGER DEFAULT 0,
            foreclosure_note TEXT,
            occupancy_status TEXT,
            is_vacant INTEGER DEFAULT 0,
            occupancy_difficulty TEXT,
            risk_level TEXT,
            risk_reason TEXT,
            analysis_explanation TEXT,
            analysis_version INTEGER DEFAULT 1,
            analysis_date TEXT,
            created_at TEXT,
            updated_at TEXT
        )""")
        logger.info("rights_summary 생성 완료")

        # 8. rights_analysis_history
        conn.execute("""
        CREATE TABLE IF NOT EXISTS rights_analysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES auction_item(id),
            analysis_version INTEGER,
            risk_level TEXT,
            risk_reason TEXT,
            total_tenant_count INTEGER,
            dangerous_tenant_count INTEGER,
            estimated_inheritance INTEGER,
            occupancy_difficulty TEXT,
            analysis_explanation TEXT,
            analysis_snapshot TEXT,
            trigger TEXT,
            analyzed_at TEXT
        )""")
        logger.info("rights_analysis_history 생성 완료")

        # 인덱스
        #
        # ★ 2026-08-26 (migration 021): 여기서 만들던 것 중 **마이그레이션 008이 같은 열로
        #   똑같이 만드는 4개**를 걷어냈다 — idx_ai_case_no / idx_ai_auction_date /
        #   idx_minimum_bid_price / idx_rs_item_id. 두 계통이 서로를 모르고 각자 만들어
        #   같은 컬럼에 인덱스가 둘씩 있었고, 읽기 이득은 0인 채 쓰기 비용과 파일 크기만
        #   늘었다(500,000행 실측: 인덱스 생성 18.4% / 파일 10.5% = 34.9MB 손해).
        #   021이 기존 DB에서 그 5쌍을 지우는데, 이 목록을 그대로 두면 **이 스크립트를
        #   다시 돌리는 순간 되살아난다** — 그래서 여기서도 함께 뺀다.
        #
        #   `idx_ai_sido`는 **남긴다.** 접두 중복(⊂ idx_search_main)이라 지우고 싶어지지만,
        #   같은 측정에서 지웠더니 sido 검색이 38ms -> 244ms(+540%)가 됐다. 좁은 인덱스는
        #   엔트리가 작아 범위/커버링 스캔에서 읽는 페이지가 훨씬 적다. 021의 주석 참고.
        indexes = [
            # 기본 조회
            "CREATE INDEX IF NOT EXISTS idx_ai_sido ON auction_item(sido)",
            # 검색 API 복합 인덱스
            "CREATE INDEX IF NOT EXISTS idx_search_main ON auction_item(sido, sigungu, property_type, auction_date)",
            "CREATE INDEX IF NOT EXISTS idx_fail_count_date ON auction_item(fail_count, auction_date)",
            "CREATE INDEX IF NOT EXISTS idx_status_date ON auction_item(status, auction_date)",
            # 관계 인덱스
            "CREATE INDEX IF NOT EXISTS idx_tr_item_id ON tenant_rights(item_id)",
            "CREATE INDEX IF NOT EXISTS idx_rs_risk ON rights_summary(risk_level)",
            "CREATE INDEX IF NOT EXISTS idx_ds_item_id ON document_status(item_id)",
        ]
        for idx in indexes:
            conn.execute(idx)
        logger.info("인덱스 생성 완료")

        conn.commit()
        logger.info("v4.1 마이그레이션 완료")

        # 결과 확인
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        print("")
        print("=== 현재 테이블 목록 ===")
        for t in tables:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
            print(f"  {t[0]}: {cnt}건")

        print("")
        print("=== 인덱스 목록 ===")
        indexes_list = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        ).fetchall()
        for idx in indexes_list:
            print(f"  {idx[0]}")

    except Exception as e:
        conn.rollback()
        logger.error("마이그레이션 실패: %s", str(e))
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
