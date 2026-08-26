# -*- coding: utf-8 -*-
"""실 DB 사본을 뜨는 방식이 **동시 쓰기에 안전한가** — 2026-08-26 신설.

## 왜 이 파일이 생겼나 (실측에서 나왔다)

이 저장소의 검사 10곳이 실 DB 사본을 떠서 격리한다. 전부 `shutil.copy2()` 였다.
지금까지는 문제가 드러나지 않았다 — `DojoonPass-DocWorker` 가 스케줄러에 **등록돼
있지 않아** 운영 중 DB 에 쓰는 프로세스가 사실상 없었기 때문이다.

2026-08-26 에 그 작업을 등록하고(02:00~04:00) 검증을 위해 워커를 실제로 돌렸다.
같은 시간에 스위트가 돌자 **두 검사가 붉어졌다**:

    test_crawl_orchestration.py     <- shutil.copy2 로 실 DB 사본을 뜬다
    test_worker_batching.py

둘 다 **단독으로는 통과한다.** 제품 결함이 아니라 **사본이 깨진 것**이다.
그리고 이제 이 조건은 **매일 밤 02:00~04:00 에 자동으로 만들어진다.**

이유 없이 붉어지는 검사는 결국 사람이 믿지 않게 된다 — 그게 진짜 손해다.

## 무엇을 고정하는가

    (1) 동시에 쓰는 프로세스가 있어도 스냅샷이 **항상 일관**하다
    (2) 스냅샷은 원본을 **건드리지 않는다**(읽기 전용으로 연다)
    (3) 실 DB 사본을 뜨는 코드가 **전부 한 함수를 거친다**(규칙이 두 벌이 되지 않는다)

(3) 이 없으면 새 검사가 다시 `shutil.copy2` 를 쓰고, 그 하나만 밤마다 흔들린다.

    python test_db_snapshot.py
"""
import io
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

REPO = os.path.dirname(os.path.abspath(__file__))
failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, "" if cond else " -- %s" % detail))
    if not cond:
        failures.append(name)


import storage.database as dbmod  # noqa: E402


# ---------------------------------------------------------------------------
print("\n--- 1. 동시 쓰기 중에도 스냅샷이 일관한가 ---")
# ---------------------------------------------------------------------------
# 운영 DB 를 쓰지 않는다. 같은 모양의 스크래치 DB 를 만들어 DB_PATH 를 잠시 돌린다.
_tmp = tempfile.mkdtemp(prefix="qa_snap_")
_src = os.path.join(_tmp, "auction.db")

# ★ DB 를 **충분히 크게** 만든다 (2026-08-26 정정).
#
#   처음 판은 800행/8KB 였다. 그 크기에서는 파일 복사가 **순식간에** 끝나 커밋 사이에
#   깔끔히 들어가므로, `shutil.copy2` 와 백업 API 가 **똑같이 통과한다** —
#   즉 이 검사가 둘을 구별하지 못했다. mutation 으로 실증했다(내부를 copy2 로 바꿔도 통과).
#
#   실측으로 크기를 정했다(같은 쓰기 부하, 스냅샷 12회):
#
#       8 KB       copy2 위반  0/12    backup 위반 0/12   <- 구별 못 함
#       18.3 MB    copy2 위반 10/12    backup 위반 0/12   <- 확실히 갈린다
#
#   운영 DB 는 이미 6.5MB 이고 계속 큰다. 여기서는 40,000행(약 18MB)으로 잡는다.
_PAD = "x" * 400
_c = sqlite3.connect(_src)
_c.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY, n INTEGER NOT NULL, pad TEXT)")
_c.execute("CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL,"
           " n INTEGER, pad TEXT)")
_c.execute("CREATE INDEX idx_child_parent ON child(parent_id)")
_c.executemany("INSERT INTO parent(id, n, pad) VALUES (?,?,?)",
               [(i, 0, _PAD) for i in range(20000)])
_c.executemany("INSERT INTO child(id, parent_id, n, pad) VALUES (?,?,?,?)",
               [(i, i, 0, _PAD) for i in range(20000)])
_c.commit()
_c.close()

_saved_path = dbmod.DB_PATH
dbmod.DB_PATH = _src

_stop = threading.Event()
_writer_error = []
_writes = [0]


def _hammer():
    """부모/자식을 **한 트랜잭션으로 짝지어** 계속 갱신한다.

    짝을 맞춰 쓰는 것이 핵심이다 — 찢어진 사본이면 parent.n 과 child.n 이 어긋난 채
    잡힌다. 단순 INSERT 만 하면 "행이 몇 개냐"만 달라져 일관성 위반을 못 본다.
    """
    conn = sqlite3.connect(_src, timeout=30)
    try:
        v = 0
        while not _stop.is_set():
            v += 1
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("UPDATE parent SET n=?", (v,))
                conn.execute("UPDATE child SET n=?", (v,))
                conn.commit()
                _writes[0] += 1
            except sqlite3.OperationalError:
                conn.rollback()
            # sleep 을 넣지 않는다 - 커밋 사이 간격이 벌어지면 파일 복사가 그 틈에
            # 깔끔히 들어가 버려 두 방식이 구별되지 않는다(위 크기 주석과 같은 이유).
    except Exception as exc:  # noqa: BLE001
        _writer_error.append(repr(exc))
    finally:
        conn.close()


_t = threading.Thread(target=_hammer, daemon=True)
_t.start()
time.sleep(0.2)

_inconsistent = []
_corrupt = []
_ROUNDS = 12
for _i in range(_ROUNDS):
    dest = os.path.join(_tmp, "snap_%d.db" % _i)
    dbmod.snapshot_live_db(dest)
    s = sqlite3.connect(dest)
    try:
        if s.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            _corrupt.append(_i)
        # ★ 일관성: 같은 트랜잭션으로 쓴 두 표의 값이 같아야 한다.
        pn = {r[0] for r in s.execute("SELECT DISTINCT n FROM parent")}
        cn = {r[0] for r in s.execute("SELECT DISTINCT n FROM child")}
        if pn != cn or len(pn) != 1:
            _inconsistent.append((_i, sorted(pn)[:3], sorted(cn)[:3]))
    finally:
        s.close()
        os.remove(dest)

_stop.set()
_t.join(timeout=10)
dbmod.DB_PATH = _saved_path

# ★ 2026-08-26 (`docs/BUGS.md` #226) — 임계값이 **실측 중앙값 위에 얹혀 있었다.**
#
#   이 단언의 목적은 하나다: 쓰기 스레드가 정말로 돌았는가(= 위 일관성 검사가 공허하지
#   않은가). 그런데 기준이 `> 20` 이었고, 같은 머신에서 15회 재 보니 커밋 수가
#   **15~25 (중앙값 20)** 였다. 임계값이 하필 중앙값이라 **15회 중 8회가 실패**한다.
#   제품이 아니라 부하가 결정하는 숫자였다.
#
#   ★ 처음에는 "스냅샷 직전에 커밋을 기다리게" 고쳐 흔들림을 없앴다. **그 고침은 틀렸다** —
#     커밋이 끝난 **직후**에 사본을 뜨게 되어 가장 조용한 순간을 고르는 셈이라,
#     `shutil.copy2` 로 되돌리는 변이를 **5회 중 0회**밖에 못 잡았다(원래 판은 5/5 검출).
#     흔들림은 사라지고 검출력도 함께 사라졌다. 그래서 되돌렸다 —
#     **위 스냅샷 루프는 손대지 않는다. 겹침이 이 검사의 전부다.**
#
#   남는 것은 임계값 자체다. 스냅샷 횟수에 묶어 "스냅샷 1회당 평균 1커밋 이상"으로 둔다.
#   실측 최소 15 vs 기준 12 로 여유가 있고, 쓰기가 죽은 경우(0~few)는 그대로 잡는다.
check_true("쓰기 스레드가 실제로 돌았다(검사가 공허하지 않다)",
           _writes[0] >= _ROUNDS,
           "-> 스냅샷 %d회 동안 커밋 %d회 (기준 %d회 이상)" % (_ROUNDS, _writes[0], _ROUNDS))
check_true("쓰기 스레드에 예외가 없다", not _writer_error, _writer_error[:1])
check("★ %d회 스냅샷 전부 무결(quick_check ok)" % _ROUNDS, _corrupt, [])
check("★ %d회 스냅샷 전부 트랜잭션 일관" % _ROUNDS, _inconsistent, [])


# ---------------------------------------------------------------------------
print("\n--- 2. 스냅샷이 원본을 건드리지 않는가 ---")
# ---------------------------------------------------------------------------
_src2 = os.path.join(_tmp, "ro.db")
_c = sqlite3.connect(_src2)
_c.execute("CREATE TABLE t(id INTEGER PRIMARY KEY)")
_c.executemany("INSERT INTO t(id) VALUES (?)", [(i,) for i in range(50)])
_c.commit()
_c.close()
_before = os.path.getsize(_src2)
_before_mtime = os.path.getmtime(_src2)

dbmod.DB_PATH = _src2
_d = os.path.join(_tmp, "ro_snap.db")
dbmod.snapshot_live_db(_d)
dbmod.DB_PATH = _saved_path

check("원본 크기 무변경", os.path.getsize(_src2), _before)
check("원본 mtime 무변경", os.path.getmtime(_src2), _before_mtime)
_s = sqlite3.connect(_d)
check("스냅샷이 행을 그대로 담았다", _s.execute("SELECT COUNT(*) FROM t").fetchone()[0], 50)
_s.close()

# 원본이 읽기 전용으로 열리는지 — 쓰기를 시도하면 실패해야 한다.
_ro = sqlite3.connect("file:%s?mode=ro" % _src2.replace("\\", "/"), uri=True)
try:
    _ro.execute("INSERT INTO t(id) VALUES (9999)")
    _ro.commit()
    check_true("★ 원본을 읽기 전용으로 연다", False, "-> 쓰기가 성공해 버렸다")
except sqlite3.OperationalError:
    check_true("★ 원본을 읽기 전용으로 연다(쓰기 시도가 거부된다)", True)
finally:
    _ro.close()

import shutil as _sh  # noqa: E402
_sh.rmtree(_tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
print("\n--- 3. ★ 실 DB 사본을 뜨는 코드가 전부 이 함수를 거치는가 (소스 계약) ---")
# ---------------------------------------------------------------------------
# 규칙이 두 벌이 되면 새 검사 하나가 다시 shutil.copy2 를 쓰고, 그것만 밤마다 흔들린다.
# 문자열이 아니라 **패턴**으로 본다 - 변수명이 달라도 잡는다.
_BAD = re.compile(
    r"shutil\.copy2?\s*\(\s*[^)]*?"
    r"(DB_PATH|db_path\(\)|[\"']auction\.db[\"'])",
    re.S,
)
# 이 두 파일은 예외다:
#   storage/database.py  - snapshot_live_db 정의 자리(설명 주석에 이름이 나온다)
#   run_python_tests.py  - 실패 안내문에 옛 관례를 **문자열로** 찍는다(코드가 아니다)
_EXEMPT = {"storage/database.py", "run_python_tests.py", "test_db_snapshot.py"}

_offenders = []
_scanned = 0
for _dp, _dn, _fn in os.walk(REPO):
    _dn[:] = [d for d in _dn if d not in
              {"node_modules", ".next", "__pycache__", ".git", "documents",
               "downloads", "logs", "registry_documents", "documents_quarantine"}
              and not d.startswith(".")]
    for _f in _fn:
        if not _f.endswith(".py"):
            continue
        _rel = os.path.relpath(os.path.join(_dp, _f), REPO).replace(os.sep, "/")
        if _rel in _EXEMPT or os.path.basename(_rel).startswith(("step", "patch_", "check_")):
            continue
        _src_txt = io.open(os.path.join(_dp, _f), encoding="utf-8", errors="replace").read()
        # 주석은 뺀다 - 설명문에 옛 방식이 나오는 것은 결함이 아니다.
        _code = "\n".join(l for l in _src_txt.splitlines() if not l.lstrip().startswith("#"))
        _scanned += 1
        if _BAD.search(_code):
            _offenders.append(_rel)

check_true("검사 대상 파일을 실제로 훑었다(공허하지 않다)", _scanned > 50, "-> %d개" % _scanned)
check("★ shutil.copy 로 실 DB 사본을 뜨는 곳 없음", sorted(_offenders), [])
if _offenders:
    print("      -> storage.database.snapshot_live_db() 를 쓰라."
          " 워커가 쓰는 중이면 파일 복사는 찢어진다.")

# 자기 검증: 패턴이 실제로 잡는가(공허한 정규식이 아닌가).
check_true("자기 검증: 옛 방식 코드를 넣으면 잡는다",
           bool(_BAD.search("shutil.copy2(dbmod.DB_PATH, tmp)")))
check_true("자기 검증: 무관한 복사는 안 잡는다",
           not _BAD.search("shutil.copy2(src_pdf, dest_pdf)"))

# 실제로 검사들이 그 함수를 쓰고 있는지도 본다(대조군 - 아무도 안 쓰면 위 검사는 공허하다).
_users = []
for _f in os.listdir(REPO):
    if _f.endswith(".py") and "snapshot_live_db(" in io.open(
            os.path.join(REPO, _f), encoding="utf-8", errors="replace").read():
        _users.append(_f)
check_true("★ 실제로 snapshot_live_db 를 쓰는 파일이 여럿이다",
           len(_users) >= 8, "-> %d개: %s" % (len(_users), sorted(_users)[:12]))

print()
if failures:
    print("실패 %d건: %s" % (len(failures), failures))
    raise SystemExit(1)
print("전체 통과")
raise SystemExit(0)
