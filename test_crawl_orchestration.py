# -*- coding: utf-8 -*-
"""`mvp_scraper.run_courts()` / `main()` 의 **성패 판정 배선** 회귀 — 2026-08-24 Sprint 252 신설.

## 왜 이 파일이 생겼나

전체 스위트 합산 커버리지를 냈더니 `mvp_scraper.py` 가 **38%** 였다(122문 중 76 미실행).
미실행 구간이 한 덩어리다 — `run_courts()` 의 오케스트레이션 전체와 `main()` 의
성패 판정·종료 코드 배선이다.

그 배선이 바로 **BUGS #47 이 태어난 자리**다:

    2026-08-02 실측: 법원 60곳 중 59곳 오류 / 저장 0건인데 배치가 **성공으로 끝났다.**
    `main()` 이 `-> None` 이라 `run_daily.bat` 의 `if errorlevel 1` 이 구조적으로
    발동할 수 없었다.

Sprint 55 가 판정 자체(`models/crawl_outcome.py`)를 분리해 고쳤고 그 모델은 지금
**커버리지 100%** 다. 그런데 **그 모델을 채우는 쪽**은 한 줄도 실행되지 않고 있었다.
즉 "판정은 검증됐지만 판정에 넘길 값을 만드는 코드는 미검증"이었다.
`outcome.collected` 에 엉뚱한 값을 넣거나 `failed` 를 안 채워도 아무도 모른다.

## 어떻게 Selenium 없이 도나

`run_courts()` 가 법원마다 부르는 것은 `crawl_court(court)` 하나다. 그 이름을
**모듈 속성으로 갈아 끼워** 시나리오를 만든다(네트워크·브라우저 없음).
DB 쓰기는 `storage.database.DB_PATH` 를 스크래치 사본으로 돌려 격리한다.

    python test_crawl_orchestration.py
"""
import datetime
import io
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


class _Court(object):
    """`config.courts.CourtInfo` 자리에 넣을 최소 객체 — 이 코드가 쓰는 것은 name 뿐이다."""

    def __init__(self, name):
        self.name = name
        self.code = name


def _item(ms, case_no, item_no="1", court="QA법원"):
    """`AuctionItem` 을 제품 모델 그대로 만든다(필드 이름이 바뀌면 여기서 깨진다)."""
    return ms.AuctionItem(
        case_no=case_no,
        item_no=item_no,
        court_name=court,
        property_type="아파트",
        address="서울특별시 종로구 QA로 1 [집합건물 철근콘크리트구조 84.00㎡]",
        # 크롤 원문은 **문자열**이다("140,000,000원" 같은 표기). 정규화 전 단계라
        # 숫자를 넣으면 validator 가 .split() 에서 죽는다 - 제품 계약 그대로 맞춘다.
        appraisal_price="100,000,000원",
        minimum_bid_price="70,000,000원",
        auction_date=(datetime.date.today() + datetime.timedelta(days=10)).isoformat(),
        status="유찰 1회",
    )


def run():
    import storage.database as db

    real_db = db.DB_PATH
    if not os.path.exists(real_db):
        check_true("원본 DB 가 있다", False, real_db)
        return 1

    tmp = tempfile.mkdtemp(prefix="crawlorch_")
    scratch = os.path.join(tmp, "auction.db")
    shutil.copy2(real_db, scratch)
    db.DB_PATH = scratch

    try:
        import mvp_scraper as ms
        from models.crawl_outcome import CrawlOutcome

        # ── 부작용 격리 ────────────────────────────────────────────────────
        # 이 검사는 제품의 실제 경로를 그대로 태우므로, 막지 않으면 **운영 산출물에
        # QA 흔적을 남긴다.** 처음 돌렸을 때 실제로 둘 다 남겼다(그래서 여기 적는다):
        #
        #   logs/validation.jsonl   ValidationEngine 이 검증 결과를 append
        #                           -> `_HERE` 기준 경로라, 그 값을 스크래치로 돌리면 따라온다
        #   auction_YYYYMMDD.csv    save_csv_backup() 이 **상대경로**로 쓴다(=cwd)
        #                           -> `_HERE` 로 안 따라오므로 함수 자체를 갈아 끼운다
        #
        # 이 저장소의 다른 테스트가 지키는 규칙과 같다 — 검사는 운영 로그/산출물을
        # 건드리지 않는다(그 흔적이 나중에 진짜 크롤 기록으로 오독된다).
        real_here = ms._HERE
        real_csv = ms.save_csv_backup
        os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
        ms._HERE = tmp
        csv_calls = {"n": 0}

        def _no_csv(rows_):
            csv_calls["n"] += 1
            return os.path.join(tmp, "qa-skipped.csv")

        ms.save_csv_backup = _no_csv

        real_crawl = ms.crawl_court
        courts3 = [_Court("QA1"), _Court("QA2"), _Court("QA3")]

        # ── 1. 전 법원이 예외 -> "전 법원 수집 실패" ──────────────────────
        def boom(court):
            raise RuntimeError("QA 주입 실패")

        ms.crawl_court = boom
        oc = CrawlOutcome()
        rows = ms.run_courts(courts3, oc)
        check("전 법원 실패: rows", rows, [])
        check("전 법원 실패: outcome.courts", oc.courts, 3)
        check("전 법원 실패: failed 목록", sorted(oc.failed), ["QA1", "QA2", "QA3"])
        check("전 법원 실패: collected", oc.collected, 0)
        check_true("★ 전 법원 실패가 치명적 실패로 판정된다",
                   (oc.failure_reason() or "").startswith("전 법원"),
                   "-> %r" % oc.failure_reason())
        check("★ 전 법원 실패의 종료 코드", oc.exit_code(), 1)

        # ── 2. 전 법원이 빈 목록 -> 스킵으로 세고 "수집 0건" ──────────────
        ms.crawl_court = lambda court: []
        oc = CrawlOutcome()
        rows = ms.run_courts(courts3, oc)
        check("전부 빈 목록: skipped", sorted(oc.skipped), ["QA1", "QA2", "QA3"])
        check("전부 빈 목록: failed", oc.failed, [])
        check_true("★ 수집 0건이 치명적 실패로 판정된다",
                   (oc.failure_reason() or "").startswith("수집 건수 0건"),
                   "-> %r" % oc.failure_reason())
        check("★ 수집 0건의 종료 코드", oc.exit_code(), 1)

        # ── 3. 섞임: 성공 1 / 빈 목록 1 / 예외 1 ──────────────────────────
        def mixed(court):
            if court.name == "QA1":
                return [_item(ms, "2099타경1001"), _item(ms, "2099타경1002")]
            if court.name == "QA2":
                return []
            raise RuntimeError("QA3 실패")

        ms.crawl_court = mixed
        oc = CrawlOutcome()
        rows = ms.run_courts(courts3, oc)
        check("섞임: collected(수집 건수)", oc.collected, 2)
        check("섞임: skipped", oc.skipped, ["QA2"])
        check("섞임: failed", oc.failed, ["QA3"])
        check_true("섞임: 정규화된 rows 가 나온다", len(rows) == 2, "-> %d행" % len(rows))
        check_true("★ 부분 실패는 치명적 실패가 아니다(임의 임계값을 만들지 않는다)",
                   oc.failure_reason() is None, "-> %r" % oc.failure_reason())
        check("★ 부분 실패의 종료 코드", oc.exit_code(), 0)
        # 저장까지 실제로 됐는가 — outcome 이 DB 결과를 담는다는 계약
        check_true("섞임: DB 저장 건수가 outcome 에 담긴다",
                   oc.persisted == 2, "-> inserted=%s updated=%s failed=%s"
                   % (oc.inserted, oc.updated, oc.upsert_failed))

        con = sqlite3.connect(scratch)
        try:
            saved = con.execute(
                "SELECT COUNT(*) FROM auction WHERE case_no LIKE '2099타경10%'").fetchone()[0]
        finally:
            con.close()
        check("섞임: 스크래치 DB 에 실제로 들어갔다", saved, 2)

        # ── 4. 수집은 됐는데 DB 저장이 0건 -> "DB 저장 0건" ───────────────
        #    upsert_batch 를 갈아 끼워 저장 실패를 흉내 낸다.
        real_upsert = ms.upsert_batch
        ms.crawl_court = lambda court: [_item(ms, "2099타경2001")] if court.name == "QA1" else []
        ms.upsert_batch = lambda rows_: {"inserted": 0, "updated": 0, "failed": len(rows_)}
        oc = CrawlOutcome()
        ms.run_courts(courts3, oc)
        ms.upsert_batch = real_upsert
        check("저장 0건: collected", oc.collected, 1)
        check("저장 0건: persisted", oc.persisted, 0)
        check_true("★ 저장 0건이 치명적 실패로 판정된다",
                   (oc.failure_reason() or "").startswith("DB 저장 0건"),
                   "-> %r" % oc.failure_reason())
        check("★ 저장 0건의 종료 코드", oc.exit_code(), 1)

        # ── 5. main() 전체: 락/DB/큐 적재까지 배선이 이어지는가 ────────────
        real_all = ms.ALL_COURTS
        real_enqueue = ms.enqueue_documents
        enqueued = {"calls": 0, "rows": 0}

        def spy_enqueue(rows_):
            enqueued["calls"] += 1
            enqueued["rows"] = len(rows_)
            return real_enqueue(rows_)

        ms.ALL_COURTS = [_Court("QA1")]
        ms.crawl_court = lambda court: [_item(ms, "2099타경3001"), _item(ms, "2099타경3002")]
        ms.enqueue_documents = spy_enqueue
        try:
            rc = ms.main()
        finally:
            ms.ALL_COURTS = real_all
            ms.enqueue_documents = real_enqueue
        check("★ main() 정상 경로의 종료 코드", rc, 0)
        check("★ main() 이 document_queue 적재를 호출한다", enqueued["calls"], 1)
        check("main() 이 넘긴 행 수", enqueued["rows"], 2)

        # ── 6. main() 실패 경로: 전 법원 실패 -> 종료 코드 1 ──────────────
        ms.ALL_COURTS = [_Court("QA1"), _Court("QA2")]
        ms.crawl_court = boom
        calls_before = enqueued["calls"]
        ms.enqueue_documents = spy_enqueue
        try:
            rc = ms.main()
        finally:
            ms.ALL_COURTS = real_all
            ms.enqueue_documents = real_enqueue
            ms.crawl_court = real_crawl
        check("★ main() 실패 경로의 종료 코드(.bat 의 errorlevel 1 이 발동한다)", rc, 1)
        check("실패 시에는 큐 적재를 부르지 않는다", enqueued["calls"], calls_before)

        # CSV 백업 경로가 실제로 불렸는지(=우리가 막지 않았다면 파일이 생겼을지) 확인한다.
        # 0이면 이 격리가 **공허**하다는 뜻이라 함께 검사한다.
        check_true("검사가 공허하지 않다(CSV 백업 경로를 실제로 지나갔다)",
                   csv_calls["n"] >= 1, "-> %d회" % csv_calls["n"])

    finally:
        try:
            ms._HERE = real_here
            ms.save_csv_backup = real_csv
        except NameError:
            pass
        db.DB_PATH = real_db
        shutil.rmtree(tmp, ignore_errors=True)

    # 운영 DB 오염 검사 — 이 파일이 스크래치만 썼다는 주장을 실제로 확인한다.
    con = sqlite3.connect("file:%s?mode=ro" % real_db.replace("\\", "/"), uri=True)
    try:
        leaked = con.execute(
            "SELECT COUNT(*) FROM auction WHERE case_no LIKE '2099타경%'").fetchone()[0]
        leaked_q = con.execute(
            "SELECT COUNT(*) FROM document_queue WHERE case_no LIKE '2099타경%'").fetchone()[0]
    finally:
        con.close()
    check("★ 운영 DB(auction)에 QA 행이 새지 않았다", leaked, 0)
    check("★ 운영 DB(document_queue)에 QA 행이 새지 않았다", leaked_q, 0)

    # 운영 **산출물** 오염 검사 — DB 말고도 새는 자리가 있다(처음에 실제로 샜다).
    root = os.path.dirname(os.path.abspath(__file__))
    vlog = os.path.join(root, "logs", "validation.jsonl")
    qa_lines = 0
    if os.path.exists(vlog):
        with io.open(vlog, encoding="utf-8", errors="replace") as fh:
            qa_lines = sum(1 for line in fh if "2099타경" in line)
    check("★ 운영 logs/validation.jsonl 에 QA 기록이 새지 않았다", qa_lines, 0)

    today_csv = os.path.join(root, "auction_%s.csv" % datetime.date.today().strftime("%Y%m%d"))
    check_true("★ 저장소 루트에 QA CSV 백업이 생기지 않았다",
               not os.path.exists(today_csv),
               "-> %s 가 생겼다(save_csv_backup 격리 실패)" % os.path.basename(today_csv))

    # ── CSV 백업이 **cwd 를 따라가지 않는가** (2026-08-24 Sprint 252) ──────
    #
    # Sprint 245/246 이 cwd 의존을 네 군데 고쳤는데 `save_csv_backup()` 하나가 남아
    # 있었다 — `df.to_csv("auction_YYYYMMDD.csv")` 가 상대경로라 **실행한 폴더**에
    # 떨어졌다. `.bat` 은 `cd /d %~dp0` 로 보호되지만 수동 실행/서비스 등록은 아니다.
    #
    # 정적 감사(test_schema_hygiene 의 cwd 검사)는 이 모양을 구조적으로 못 잡는다:
    # 그쪽은 알려진 경로 호출에 **문자열 리터럴**이 들어가는 경우만 본다. 여기는
    # pandas `to_csv` 이고 인자도 조립된 변수다. 그래서 **다른 cwd 에서 실제로 돌린다** —
    # Sprint 246 이 쓴 방법(별도 프로세스 + cwd 만 바꿔 재현) 그대로다.
    import subprocess

    probe_dir = tempfile.mkdtemp(prefix="cwdprobe_")
    root = os.path.dirname(os.path.abspath(__file__))
    code = (
        "import sys, os, json;"
        " sys.path.insert(0, r'%s');"
        " import mvp_scraper as ms;"
        " rows=[{'case_no':'2099타경9001','court_name':'QA','item_no':'1'}];"
        " print(json.dumps({'ret': ms.save_csv_backup(rows), 'cwd': os.getcwd()}))"
    ) % root
    written = None
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=probe_dir,
                           capture_output=True, timeout=300,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        out = (r.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        payload = None
        for line in reversed(out):
            if line.startswith("{"):
                payload = __import__("json").loads(line)
                break
        check_true("다른 cwd 에서 save_csv_backup 이 실행됐다", payload is not None,
                   "-> stdout=%r stderr=%r" % (out[-3:], (r.stderr or b'')[-300:]))
        if payload:
            written = payload["ret"]
            stray = [f for f in os.listdir(probe_dir) if f.endswith(".csv")]
            check("★ CSV 백업이 실행 폴더(cwd)에 떨어지지 않는다", stray, [])
            check_true("★ CSV 백업이 저장소(모듈 위치) 안에 생긴다",
                       os.path.dirname(os.path.abspath(written)) == root,
                       "-> %s" % written)
    finally:
        # 이 검사가 만든 CSV 는 이 검사가 치운다(운영 산출물을 남기지 않는다).
        if written and os.path.exists(written):
            os.remove(written)
        shutil.rmtree(probe_dir, ignore_errors=True)

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
