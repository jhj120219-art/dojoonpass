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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.dirname(os.path.abspath(__file__))

def run():
    # 마이그레이션은 FK 강제를 끈 커넥션으로 실행한다.
    # SQLite에서 UNIQUE 제약을 바꾸려면 "새 테이블 생성 → 이관 → DROP → RENAME" 패턴을 써야
    # 하는데, DROP 직후 RENAME 전까지 자식 행이 잠시 고아가 된다. FK를 켠 채로는 그 지점에서
    # 마이그레이션 자체가 실패한다. 런타임(API/크롤러)은 기본값대로 FK가 켜진 커넥션을 쓴다.
    conn = get_connection(enforce_foreign_keys=False)
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
