"""자산 기록 경로의 **실패 분기** — 2026-08-17 Sprint 164 신설.

## 왜 이 파일이 생겼나

커버리지를 전 파일로 다시 재니 `storage/database.py` 가 88% 였고, 남은 46줄 중
`query()`(프로덕션 호출부 0개, Sprint 146 §J-5 참조)를 빼면 **전부 자산 기록 경로의
방어 분기**였다.

```
storage\database.py   395 stmts  46 miss  88%
   877-878    _sha256_file          파일을 못 읽을 때
   892-894    _pdf_page_count       pdfplumber 없음
   915-916    to_relative_storage_path  루트 밖 경로
   948-955    _record_doc_raw       대상 물건 없음 / 알 수 없는 doc_type
   965-973    _record_doc_raw       대표 파일 결정 실패 시 fallback
   1027-1049  save_auction_images   대상 없음 / 잘못된 항목 / 0바이트
```

이 분기들이 지키는 것이 이 저장소의 단골 결함이다 —
**"없는 파일을 수집 완료로 기록하는 것".** doc_raw/auction_image 에 행이 생기면
화면은 "문서 있음"으로 표시하고, 사용자는 눌렀을 때 빈 화면을 본다. 오류 메시지도 없다.

정상 경로는 `test_asset_pipeline.py` 가 이미 덮는다. **덮이지 않은 것은 "저장했다는
파일이 실제로는 없을 때"** 이고, 그때 행이 생기지 않아야 한다는 것이 핵심 계약이다.

## 무엇을 단언하나

각 실패마다 두 가지다.

1. **예외로 터지지 않는다** — 자산 기록이 크롤 전체를 죽이면 안 된다.
2. **거짓 성공 행이 남지 않는다** — 이것이 본질이다. 조용히 넘어가는 것과
   "수집했다고 DB 에 적는 것"은 완전히 다른 문제다.

## Mutation 결과 — 3개 중 1개는 **일부러 살려 두었다**

```
M1 0바이트 이미지 가드 제거         exit=1 잡힘   [FAIL] 하나도 저장되지 않았다: 1 (expected 0)
M2 이미지 "파일 없음" 가드 제거      exit=0 살아남음
M3 잘못된 항목(seq/path) 가드 제거   exit=1 잡힘
```

M2 가 살아남은 이유를 확인했다. `except OSError` 를 지우고 `size = 0` 으로 떨어뜨리면
**바로 다음 줄의 `if size <= 0` 가드가 같은 항목을 걸러 낸다.** 즉 없는 파일은
**두 겹으로** 막혀 있고, 한 겹을 걷어내도 계약("없는 파일은 기록되지 않는다")은 그대로다.

이건 테스트가 약한 것이 아니라 **코드가 겹쳐 방어하고 있는 것**이다. 두 겹을 구분하려면
로그 문구를 단언해야 하는데, 그건 계약이 아니라 구현을 고정하는 일이라 하지 않았다.
(Sprint 158 의 `conn.rollback()` equivalent mutant 과 같은 판단이다.)

## 운영 DB 를 건드리지 않는다

`test_asset_pipeline.Env`(임시 DB + 임시 문서 루트, 실제 부트스트랩 스키마)를 재사용한다.

    python test_asset_record_failures.py
"""
import os
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


def _count(env, table, **where):
    conn = env.conn()
    try:
        if where:
            k, v = next(iter(where.items()))
            return conn.execute("SELECT COUNT(*) FROM %s WHERE %s=?" % (table, k), (v,)).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. 순수 함수의 실패 처리 — 터지지 않고 "모른다"를 정확히 표현한다
# ---------------------------------------------------------------------------
def test_pure_helpers_fail_safely():
    print("\n--- 1. 해시 / 쪽수 / 상대경로 ---")
    from storage.database import _sha256_file, _pdf_page_count, to_relative_storage_path

    missing = os.path.join(tempfile.gettempdir(), "qa_no_such_file_%d.bin" % os.getpid())
    check("없는 파일의 해시는 빈 문자열(예외 아님)", _sha256_file(missing), "")

    # ★ None 과 0 을 구분하는 것이 계약이다. 0 은 "0쪽짜리 PDF"라는 거짓말이 되고
    #   뷰어가 페이지 이동을 아예 못 그린다. 모르면 None 이어야 한다.
    check("PDF 가 아니면 쪽수는 None", _pdf_page_count(missing + ".txt"), None)
    check("없는 PDF 의 쪽수도 None(0 아님)", _pdf_page_count(missing + ".pdf"), None)

    # 루트 밖 경로는 추측해서 자르지 않고 원본을 그대로 둔다.
    outside = os.path.join(tempfile.gettempdir(), "qa_outside", "a.pdf")
    check("루트 밖 절대경로는 그대로 둔다", to_relative_storage_path(outside), outside)

    # 루트 안 경로는 상대경로 + 슬래시 정규화.
    root = os.path.dirname(os.path.abspath(__file__))
    inside = os.path.join(root, "documents", "법원", "사건", "1", "spec.pdf")
    rel = to_relative_storage_path(inside)
    check_true("루트 안 경로는 상대경로가 된다", not os.path.isabs(rel), rel)
    check_true("구분자를 '/'로 정규화한다", "\\" not in rel, rel)


# ---------------------------------------------------------------------------
# 2. ★★ 대상 물건이 없으면 doc_raw 에 아무것도 적지 않는다
# ---------------------------------------------------------------------------
def test_doc_raw_no_target_records_nothing():
    print("\n--- 2. doc_raw: 대상 물건 없음 ---")
    import test_asset_pipeline as tap
    from storage.database import _record_doc_raw

    env = tap.Env()
    try:
        conn = env.conn()
        try:
            before = conn.execute("SELECT COUNT(*) FROM doc_raw").fetchone()[0]
            # 존재하지 않는 (법원, 사건, 물건)
            _record_doc_raw(conn, "없는법원", "9999타경999999", "1", "spec",
                            [os.path.abspath(__file__)], "2026-08-17T00:00:00")
            conn.commit()
            after = conn.execute("SELECT COUNT(*) FROM doc_raw").fetchone()[0]
        finally:
            conn.close()
        check("★ 대상이 없으면 doc_raw 행이 늘지 않는다", after, before)
    finally:
        env.close()


# ---------------------------------------------------------------------------
# 3. ★ 알 수 없는 doc_type / 사진은 doc_raw 에 들어가지 않는다
# ---------------------------------------------------------------------------
def test_doc_raw_rejects_unknown_and_image_type():
    print("\n--- 3. doc_raw: 알 수 없는 종류 / image ---")
    import test_asset_pipeline as tap
    from storage.database import _record_doc_raw

    env = tap.Env()
    env.seed_item(item_id=1)
    try:
        conn = env.conn()
        try:
            row = conn.execute(
                "SELECT court_name, case_no, item_no FROM auction_item WHERE id=1").fetchone()
            court, case_no, item_no = row[0], row[1], str(row[2])
            before = conn.execute("SELECT COUNT(*) FROM doc_raw").fetchone()[0]

            _record_doc_raw(conn, court, case_no, item_no, "bogus_type",
                            [os.path.abspath(__file__)], "2026-08-17T00:00:00")
            # 사진은 auction_image 담당 — doc_raw 는 (item, doc_type)당 1행이라 담을 수 없다.
            _record_doc_raw(conn, court, case_no, item_no, "image",
                            [os.path.abspath(__file__)], "2026-08-17T00:00:00")
            conn.commit()
            after = conn.execute("SELECT COUNT(*) FROM doc_raw").fetchone()[0]
        finally:
            conn.close()
        check("★ 알 수 없는 종류 / image 는 doc_raw 에 들어가지 않는다", after, before)
    finally:
        env.close()


# ---------------------------------------------------------------------------
# 4. ★★ 저장했다는 파일이 실제로 없으면 기록하지 않는다
#
# 이것이 이 파일의 핵심이다. 행이 생기면 화면은 "문서 있음"으로 표시하고
# 사용자는 빈 화면을 본다 — 오류 메시지도 없다.
# ---------------------------------------------------------------------------
def test_doc_raw_missing_file_records_nothing():
    print("\n--- 4. doc_raw: 저장했다는 파일이 없다 ---")
    import test_asset_pipeline as tap
    from storage.database import _record_doc_raw

    env = tap.Env()
    env.seed_item(item_id=1)
    try:
        conn = env.conn()
        try:
            row = conn.execute(
                "SELECT court_name, case_no, item_no FROM auction_item WHERE id=1").fetchone()
            court, case_no, item_no = row[0], row[1], str(row[2])
            before = conn.execute("SELECT COUNT(*) FROM doc_raw").fetchone()[0]
            ghost = os.path.join(tempfile.gettempdir(), "qa_ghost_%d.pdf" % os.getpid())
            check_true("사전 조건: 그 파일은 없다", not os.path.exists(ghost))

            _record_doc_raw(conn, court, case_no, item_no, "spec", [ghost],
                            "2026-08-17T00:00:00")
            conn.commit()
            after = conn.execute("SELECT COUNT(*) FROM doc_raw").fetchone()[0]
        finally:
            conn.close()
        check("★★ 없는 파일은 doc_raw 에 기록되지 않는다", after, before)
    finally:
        env.close()


# ---------------------------------------------------------------------------
# 5. ★★ auction_image: 없는 파일 / 0바이트 / 잘못된 항목은 건너뛴다
# ---------------------------------------------------------------------------
def test_images_skip_missing_zero_and_malformed():
    print("\n--- 5. auction_image: 없는 파일 / 0바이트 / 잘못된 항목 ---")
    import test_asset_pipeline as tap
    from storage.database import save_auction_images

    env = tap.Env()
    env.seed_item(item_id=1)
    try:
        conn = env.conn()
        try:
            row = conn.execute(
                "SELECT court_name, case_no, item_no FROM auction_item WHERE id=1").fetchone()
            court, case_no, item_no = row[0], row[1], str(row[2])
        finally:
            conn.close()

        tmpdir = tempfile.mkdtemp(prefix="qa_img_")
        zero = os.path.join(tmpdir, "zero.jpg")
        open(zero, "wb").close()                      # 0바이트
        ghost = os.path.join(tmpdir, "ghost.jpg")     # 아예 없음

        result = save_auction_images(court, case_no, item_no, [
            {"seq": 1, "kind": "photo", "path": ghost},        # 파일 없음
            {"seq": 2, "kind": "photo", "path": zero},         # 0바이트
            {"seq": None, "kind": "photo", "path": zero},      # seq 가 int 아님
            {"seq": 4, "kind": "photo", "path": None},         # path 없음
        ])
        print("      반환:", result)
        check("★★ 하나도 저장되지 않았다", result.get("saved"), 0)
        check("★ 네 건 모두 건너뛴 것으로 집계된다", result.get("skipped_missing"), 4)
        check("★★ auction_image 행이 0이다", _count(env, "auction_image"), 0)
    finally:
        env.close()


# ---------------------------------------------------------------------------
# 6. ★ auction_image: 대상 물건이 없으면 전부 건너뛴다
# ---------------------------------------------------------------------------
def test_images_no_target():
    print("\n--- 6. auction_image: 대상 물건 없음 ---")
    import test_asset_pipeline as tap
    from storage.database import save_auction_images

    env = tap.Env()
    try:
        result = save_auction_images("없는법원", "9999타경999999", "1", [
            {"seq": 1, "kind": "photo", "path": os.path.abspath(__file__)},
        ])
        print("      반환:", result)
        check("★ 저장 0", result.get("saved"), 0)
        check("★ 건너뛴 수가 입력 수와 같다", result.get("skipped_missing"), 1)
        check("★ auction_image 행이 0이다", _count(env, "auction_image"), 0)
    finally:
        env.close()


# ---------------------------------------------------------------------------
# 7. 대조군 — 정상 파일은 실제로 기록된다 (위 검사들이 "항상 0"이 아님을 증명)
# ---------------------------------------------------------------------------
def test_valid_image_is_recorded():
    print("\n--- 7. 대조군: 정상 파일은 기록된다 ---")
    import test_asset_pipeline as tap
    from storage.database import save_auction_images

    env = tap.Env()
    env.seed_item(item_id=1)
    try:
        conn = env.conn()
        try:
            row = conn.execute(
                "SELECT court_name, case_no, item_no FROM auction_item WHERE id=1").fetchone()
            court, case_no, item_no = row[0], row[1], str(row[2])
        finally:
            conn.close()

        tmpdir = tempfile.mkdtemp(prefix="qa_img_ok_")
        good = os.path.join(tmpdir, "good.jpg")
        with open(good, "wb") as f:
            # ★ `MIN_IMAGE_BYTES`(1,024)를 넘겨야 한다 (2026-08-19 Sprint 218, BUGS #148).
            #   그 아래는 저장 계층이 기록하지 않는다 — 기록하면 화면은 사진이 있다고
            #   하는데 서빙은 404 가 되기 때문이다. 예전 500바이트 픽스처는
            #   **실제로는 한 장도 서빙될 수 없는 크기**였다.
            f.write(b"\xff\xd8\xff" + b"x" * 2048)     # 0바이트가 아닌 실제 내용

        result = save_auction_images(court, case_no, item_no, [
            {"seq": 1, "kind": "photo", "path": good},
        ])
        print("      반환:", result)
        check("★ 정상 파일은 저장된다", result.get("saved"), 1)
        check("★ auction_image 행이 1이다", _count(env, "auction_image"), 1)
    finally:
        env.close()


if __name__ == "__main__":
    test_pure_helpers_fail_safely()
    test_doc_raw_no_target_records_nothing()
    test_doc_raw_rejects_unknown_and_image_type()
    test_doc_raw_missing_file_records_nothing()
    test_images_skip_missing_zero_and_malformed()
    test_images_no_target()
    test_valid_image_is_recorded()

    print("\n" + "=" * 60)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL ASSET RECORD FAILURE TESTS PASSED")
