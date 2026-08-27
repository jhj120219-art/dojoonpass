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
import sqlite3

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.dirname(os.path.abspath(__file__))


def _is_executable_sql(chunk: str) -> bool:
    """주석과 공백만 남는 조각인가? (그런 조각을 execute 하면 예외가 된다)"""
    body = "\n".join(
        line for line in (chunk or "").splitlines()
        if not line.strip().startswith("--")
    )
    return bool(body.strip(" \t\r\n;"))


def split_sql_statements(script: str):
    """마이그레이션 파일을 **문장 하나씩** 내놓는다.

    왜 직접 쪼개는가 — `executescript()` 를 못 쓰기 때문이다(`run()` 주석 참고).
    한 파일을 한 트랜잭션으로 묶으려면 문장을 `execute()` 로 하나씩 넣어야 하고,
    그러려면 경계를 알아야 한다.

    경계 판정은 **직접 하지 않는다.** `sqlite3.complete_statement()` 는 SQLite 자신의
    토크나이저다 — 주석 안의 세미콜론(`-- 경계가 아니다;`)과 문자열 리터럴 안의
    세미콜론(`DEFAULT 'a;b'`)을 정확히 건너뛴다. 정규식으로 `;` 를 쪼개면 이 저장소의
    실제 파일에서 바로 깨진다(013/016/023 에 여러 줄 CREATE TABLE 이 있다).

    파일 끝에 주석만 남는 꼬리는 버린다 — `013`/`021` 처럼 마지막 문장 뒤에 설명이
    붙는 파일이 있고, 주석뿐인 문자열을 `execute()` 에 넣으면 예외가 난다.
    """
    buf = ""
    for line in (script or "").splitlines(keepends=True):
        buf += line
        if _is_executable_sql(buf) and sqlite3.complete_statement(buf):
            yield buf
            buf = ""
    if _is_executable_sql(buf):
        yield buf

def run():
    """마이그레이션을 적용한다. 커넥션은 **어떤 경로로 끝나든** 닫는다.

    닫기를 `finally` 로 옮긴 이유 (2026-08-27, 자원 누수 감사):
    예전에는 마지막 줄에서만 `conn.close()` 했다. 그래서 마이그레이션이 실패해
    예외가 올라가면 커넥션이 열린 채로 남았다. 운영에서는 프로세스가 곧 끝나 OS 가
    회수하므로 드러나지 않지만, **같은 프로세스 안에서 러너를 여러 번 부르는
    검사**(`test_bootstrap.py`, `test_schema_hygiene.py` §7)에서는 다르다 —
    Windows 는 열린 핸들이 있는 파일을 지우지 못해 스크래치 DB 정리가 실패하고,
    남은 잠금이 다음 검사에 엉뚱한 실패로 나타난다.
    """
    # 마이그레이션은 FK 강제를 끈 커넥션으로 실행한다.
    # SQLite에서 UNIQUE 제약을 바꾸려면 "새 테이블 생성 → 이관 → DROP → RENAME" 패턴을 써야
    # 하는데, DROP 직후 RENAME 전까지 자식 행이 잠시 고아가 된다. FK를 켠 채로는 그 지점에서
    # 마이그레이션 자체가 실패한다. 런타임(API/크롤러)은 기본값대로 FK가 켜진 커넥션을 쓴다.
    conn = get_connection(enforce_foreign_keys=False)
    try:
        _apply_all(conn)
    finally:
        conn.close()


def _apply_all(conn):
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
        # 닫기는 `run()` 의 finally 가 한다 — 여기서 또 닫으면 이중 close 다.
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

        # ★ 한 파일 = 한 트랜잭션. 전부 적용되거나 전부 없던 일이 된다.
        #   (2026-08-27, docs/BUGS.md — 크롤->DB 경로 감사)
        #
        #   예전에는 `conn.executescript(sql)` 이었다. 이 메서드는 **먼저 커밋하고
        #   스크립트를 트랜잭션 밖에서** 돌린다. 파일에 BEGIN/COMMIT 이 없으면
        #   (이 폴더의 파일 전부가 그렇다) 각 문장이 **즉시 확정**된다. 실측했다:
        #
        #     "ALTER ADD COLUMN a; SELECT 없는컬럼;"  -> 예외가 났는데 a 는 남는다
        #     "INSERT ...; ALTER ...; SELECT 없는컬럼;" -> 둘 다 남는다(DML 이 있어도 같다)
        #     "CREATE t_new; DROP t; RENAME; SELECT 없는컬럼;" -> **t 의 행이 사라진다**
        #
        #   결과가 두 갈래로 나쁘다.
        #
        #   (1) 되돌아오지 않는다. 실패한 파일은 `migration_history` 에 안 들어가므로
        #       다음 실행이 **처음부터 다시** 적용한다. 그런데 앞부분은 이미 적용돼 있어
        #       `ALTER TABLE ADD COLUMN` 이 `duplicate column name` 으로 죽는다.
        #       SQLite 에는 ADD COLUMN 용 IF NOT EXISTS 가 없다(025 주석이 인정한다).
        #       러너가 raise -> `run_daily.bat` 3단계 exit 1 -> **mvp_scraper.py 가
        #       아예 실행되지 않는다.** 한 번의 사고가 매일 06:00 크롤을 영구 정지시킨다.
        #
        #   (2) 023/024 는 SQLite 의 제약 변경을 위해
        #       `CREATE _new` -> `INSERT SELECT` -> `DROP 원본` -> `RENAME` 을 돈다.
        #       DROP 과 RENAME **사이**에서 죽으면 원본 테이블이 사라진 채 확정되고
        #       데이터는 `_new` 라는 엉뚱한 이름 밑에 남는다. 재실행은
        #       `INSERT ... SELECT FROM 원본` 에서 `no such table` 로 죽는다.
        #       대상이 `payment_webhooks` / `registry_credits` — 결제 테이블이다.
        #
        #   SQLite 는 MySQL/Oracle 과 달리 **DDL 도 트랜잭션에 참여한다.** 그래서
        #   파일 하나와 history INSERT 를 한 트랜잭션으로 묶는 것만으로 둘 다 사라진다.
        #   묶으려면 `executescript()` 를 버리고 문장을 직접 넣어야 한다
        #   (`split_sql_statements()` 참고 — 경계 판정은 SQLite 토크나이저에 맡긴다).
        #
        #   `PRAGMA foreign_keys` 는 커넥션 직후(트랜잭션 밖)에 이미 꺼져 있다.
        #   트랜잭션 안에서는 이 PRAGMA 가 무시되므로 순서가 이대로여야 한다.
        try:
            from datetime import datetime
            conn.execute("BEGIN")
            for stmt in split_sql_statements(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO migration_history (filename, applied_at) VALUES (?, ?)",
                (filename, datetime.now().isoformat())
            )
            conn.commit()
            logger.info("[OK] %s 적용 완료", filename)
        except Exception as e:
            # ★ 이 rollback 을 지워도 **검사는 통과한다** — `run()` 의 `finally: conn.close()`
            #   가 열린 트랜잭션을 어차피 버리기 때문이다(실측: BEGIN -> ALTER -> close 만
            #   해도 컬럼이 남지 않는다). 그래서 변이 테스트에서 이 줄만 지운 변종은
            #   아무 검사도 잡지 못한다 — **동치 변이이고, 그게 맞다.**
            #
            #   그래도 남겨 둔다: 되돌리는 시점을 close 에 맡기면, 나중에 누가 커넥션을
            #   재사용하도록 바꾸는 순간(그 자체는 자연스러운 변경이다) 열린 트랜잭션이
            #   그대로 이어져 **다음 파일이 실패한 것과 한 덩어리로 커밋된다.**
            #   여기서 명시적으로 끝내면 그 경우에도 파일 경계가 유지된다.
            try:
                conn.rollback()
            except Exception:       # noqa: BLE001 - 롤백 실패가 원인을 가리면 안 된다
                logger.exception("[FAIL] %s: 롤백도 실패", filename)
            logger.error("[FAIL] %s: %s (이 파일은 적용되지 않았다 - 고친 뒤 그대로 재실행하면 된다)",
                         filename, str(e))
            raise

    print("")
    print("=== 마이그레이션 결과 ===")
    history = conn.execute(
        "SELECT filename, applied_at FROM migration_history ORDER BY id"
    ).fetchall()
    for h in history:
        print(f"  {h['filename']} | {h['applied_at']}")

if __name__ == "__main__":
    run()
