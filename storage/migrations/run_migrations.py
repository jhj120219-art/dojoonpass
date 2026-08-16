import sys, os

# 저장소 루트를 sys.path에 넣는다. `storage/migrations/run_migrations.py`이므로
# dirname을 **세 번** 올라가야 루트다(migrations -> storage -> 루트).
# 2026-08-11 Sprint 55: 두 번만 올라가 `.../storage`를 넣고 있었다. 문서가 안내하는
# `python -m storage.migrations.run_migrations` 형태에서는 cwd가 sys.path에 들어가 우연히
# 동작했지만, `python storage/migrations/run_migrations.py`로 직접 부르면
# ModuleNotFoundError로 죽는다 — 이 줄의 목적(어디서 부르든 동작) 자체가 무효였다.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from storage.database import get_connection
import logging
import re

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.dirname(os.path.abspath(__file__))

def run():
    # 마이그레이션은 FK 강제를 끈 커넥션으로 실행한다.
    # SQLite에서 UNIQUE 제약을 바꾸려면 "새 테이블 생성 → 이관 → DROP → RENAME" 패턴을 써야
    # 하는데, DROP 직후 RENAME 전까지 자식 행이 잠시 고아가 된다. FK를 켠 채로는 그 지점에서
    # 마이그레이션 자체가 실패한다. 런타임(API/크롤러)은 기본값대로 FK가 켜진 커넥션을 쓴다.
    conn = get_connection(enforce_foreign_keys=False)

    # ── 선행 스키마 확인 (2026-08-13 Sprint 99 신설) ────────────────────────────
    #
    # 이 마이그레이션들은 **빈 DB에서 시작하지 않는다.** 008(검색 인덱스)부터
    # `auction_item`을, 011/013은 `auction_case`/`auction_item`을 이미 있다고 가정한다.
    # 그 테이블들을 만드는 것은 `storage/migrate_v4_1.py`이고, 이 러너가 아니다.
    #
    # 그래서 새로 clone한 저장소에서 안내대로 `init_db()` -> 이 러너 순으로 돌리면
    # **008에서 죽는다**(실측):
    #
    #     [FAIL] 008_create_search_indexes.sql: no such table: main.auction_item
    #
    # 더 나쁜 것은 그 다음이다 — 001~007은 이미 적용돼 `migration_history`에 남으므로
    # DB가 **절반만 마이그레이션된 상태**로 남는다. 원인 메시지는 "auction_item이 없다"뿐이라
    # 무엇을 먼저 돌려야 하는지 알 수 없다.
    #
    # 아무것도 적용하기 전에 먼저 확인하고, **무엇을 어떤 순서로 돌려야 하는지** 알려준다.
    # (올바른 순서로 돌리면 19개가 전부 적용되고 26개 테이블이 만들어지는 것을 실측 확인했다.)
    #
    # 필요 여부는 **실제 .sql 내용에서 도출한다** — 목록을 여기 박아 두면 두 가지가 어긋난다.
    # (1) 앞으로 선행 테이블을 요구하는 마이그레이션이 늘어도 이 목록이 안 따라온다.
    # (2) 테스트가 자기만의 마이그레이션 디렉터리로 러너를 부를 때, 그 SQL은 auction_item을
    #     쓰지도 않는데 무조건 막혀 버린다(`test_schema_hygiene.py`의 러너 검사가 그렇다).
    # 지금 적용할 SQL이 그 테이블을 실제로 언급할 때만 확인한다.
    #
    # 2026-08-15 Sprint 122: "auction"(레거시 크롤러 원본 테이블, init_db()가 만든다)이
    # 이 목록에 빠져 있었다. 011/012가 `FROM auction`/`DROP TABLE auction` 등으로 그
    # 테이블에 의존하는데, 빈 DB에서 안내대로 migrate_v4_1.py -> 이 러너만 돌리면(문서가
    # 실제로 그렇게 안내하고 있었다 - docs/CLAUDE.md 참고) auction_item/auction_case는
    # migrate_v4_1.py가 만들어 이 검사를 통과하지만, auction은 여전히 없어 011에서
    # `sqlite3.OperationalError: no such table: auction`로 죽는다 - 이 preflight가
    # 막아 주려던 바로 그 실패 모양인데, "auction"만 빠져서 못 잡고 있었다(실측 재현).
    PREREQ_TABLES = ("auction_item", "auction_case", "auction")
    existing = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    referenced = set()
    for _f in sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql")):
        try:
            _sql = open(os.path.join(MIGRATIONS_DIR, _f), encoding="utf-8").read()
        except OSError:
            continue
        for _t in PREREQ_TABLES:
            # `auction_item_new`처럼 새로 만드는 테이블에 오탐하지 않도록 경계를 본다.
            if re.search(r"\b%s\b(?!_new)" % re.escape(_t), _sql):
                referenced.add(_t)

    missing = [t for t in sorted(referenced) if t not in existing]
    if missing:
        conn.close()
        raise SystemExit(
            "\n[중단] 선행 스키마가 없습니다: %s\n"
            "\n이 마이그레이션들은 기존 테이블을 변경하는 것이라 빈 DB에서는 돌 수 없습니다."
            "\n아래 순서로 실행하십시오:\n"
            "\n  1) python -c \"from storage.database import init_db; init_db()\""
            "\n  2) python storage/migrate_v4_1.py"
            "\n  3) python storage/migrations/run_migrations.py   (이 스크립트)\n"
            "\n(2번이 auction_item / auction_case / document_status / tenant_rights /"
            "\n rights_summary를 만듭니다. 지금 중단했으므로 DB는 변경되지 않았습니다.)\n"
            % ", ".join(missing)
        )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS migration_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            applied_at TEXT NOT NULL
        )
    """)
    conn.commit()

    sql_files = sorted([
        f for f in os.listdir(MIGRATIONS_DIR)
        if f.endswith(".sql")
    ])

    for filename in sql_files:
        applied = conn.execute(
            "SELECT id FROM migration_history WHERE filename = ?", (filename,)
        ).fetchone()

        if applied:
            logger.info("[SKIP] %s (이미 적용됨)", filename)
            continue

        path = os.path.join(MIGRATIONS_DIR, filename)
        sql = open(path, encoding="utf-8").read()

        try:
            conn.executescript(sql)
            from datetime import datetime
            conn.execute(
                "INSERT INTO migration_history (filename, applied_at) VALUES (?, ?)",
                (filename, datetime.now().isoformat())
            )
            conn.commit()
            logger.info("[OK] %s 적용 완료", filename)
        except Exception as e:
            logger.error("[FAIL] %s: %s", filename, str(e))
            raise

    print("")
    print("=== 마이그레이션 결과 ===")
    history = conn.execute(
        "SELECT filename, applied_at FROM migration_history ORDER BY id"
    ).fetchall()
    for h in history:
        print(f"  {h['filename']} | {h['applied_at']}")

    conn.close()

if __name__ == "__main__":
    run()
