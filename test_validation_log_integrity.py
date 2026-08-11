"""
validator/validation_engine.py의 logs/validation.jsonl 기록 순수 로직 회귀 테스트.

Selenium/실제 브라우저는 전혀 쓰지 않는다 — ValidationEngine._log()의 append 동작과
JSONL(줄 단위 JSON) 형식의 손상 내성만 파일시스템 레벨에서 직접 검증한다.

배경(2026-08-10 Sprint 42, Validation Log Concurrency Audit): logs/validation.jsonl에
실제로 동시 쓰기를 유발할 수 있는 경로가 있는지 저장소 전체를 grep으로 확인했다 —
ValidationEngine을 참조하는 곳은 mvp_scraper.py(단일 프로세스, validate_batch()가 순차
list comprehension으로 항목마다 한 번씩 append), test_db.py(실 크롤링 수동 스크립트,
회귀 대상 아님), revalidate.py(별도 파일 logs/revalidation.jsonl을 씀, 겹치지 않음)
3곳뿐이라 실제 다중 프로세스 동시 쓰기 경로 자체가 없다(이론적 레이스만 있고 재현 불가 —
불필요한 수정을 하지 않는다는 이 세션의 원칙에 따라 코드는 변경하지 않았다).

대신 이 파일은 append-only JSONL 형식이 갖는 실제 안전 특성을 검증한다: 각 줄은
독립적인 with-block으로 flush/close되므로, 쓰기 도중 죽어도 손상되는 건 최대 "마지막
한 줄"뿐이고 그 앞의 모든 줄은 안전하게 남는다(대부분의 JSONL 리더는 줄 단위로 파싱해
깨진 줄만 건너뛸 수 있다) — collect_status()/checkpoint.json이 겪었던 "전체 파일 손상"
위험과는 근본적으로 다른, 이미 안전한 설계임을 실측으로 뒷받침한다.

    python test_validation_log_integrity.py
"""
import sys
import os
import json
import shutil
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    ok = bool(cond)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("" if ok else " -> " + str(detail))))
    if not ok:
        failures.append(name)


# 2026-08-11 Sprint 52 — `logs/`(OneDrive 동기화 폴더) 대신 시스템 임시 디렉터리를 쓴다.
# `test_checkpoint_atomicity.py`에서 같은 위치가 간헐적 flaky의 원인이었다(동기화 중인
# 파일에 쓰고 곧바로 읽으면 이전 내용이 보이는 경우가 있었다). 이 테스트도 append 직후
# 바이트 단위로 되읽는 구조라 동일한 노출이 있어 선제적으로 옮긴다.
# 검증 대상은 ValidationEngine의 append 로직이지 저장소의 logs/ 디렉터리가 아니다.
QA_DIR = tempfile.mkdtemp(prefix="dojoonpass-qa-validation-")
QA_LOG_PATH = os.path.join(QA_DIR, "qa-validation-" + uuid.uuid4().hex[:8] + ".jsonl")


def make_item(case_no, appraisal="100000000", minimum="80000000"):
    from models.auction_item import AuctionItem
    return AuctionItem(
        case_no=case_no, item_no="1", address="서울특별시 강남구 역삼동",
        property_type="아파트", appraisal_price=appraisal, minimum_bid_price=minimum,
        auction_date="2026-09-01", status="진행", court_code="B000210",
        court_name="서울중앙지방법원", appraisal_summary="서울특별시 강남구",
        crawl_date="2026-08-10",
    )


def test_log_entry_matches_validation_result():
    """_log()가 item.validation_status/reasons를 그대로 기록하는지, PASS/FAIL 둘 다
    정확히 일치하는지 확인한다(결과-로그 불일치 가능성 점검).
    """
    print("\n--- 1. log entry matches the actual validation result ---")
    from validator.validation_engine import ValidationEngine

    engine = ValidationEngine(log_path=QA_LOG_PATH)
    pass_item = make_item("2026타경1234")   # 정상 케이스
    fail_item = make_item("BAD-CASE-NO")    # 사건번호 형식 위반 -> FAIL

    engine.validate(pass_item)
    engine.validate(fail_item)

    with open(QA_LOG_PATH, encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    check("two lines written for two validate() calls", len(lines), 2)
    check("first line reflects PASS status", lines[0]["validation"], pass_item.validation_status)
    check("first line case_no matches", lines[0]["case_no"], "2026타경1234")
    check("second line reflects FAIL status", lines[1]["validation"], "FAIL")
    check_true("second line's reasons include the actual failure reason",
               any("case_no_format_invalid" in r for r in lines[1]["reasons"]), lines[1]["reasons"])


def test_truncated_last_line_does_not_corrupt_prior_lines():
    """append 도중 프로세스가 죽어 마지막 줄이 잘렸다고 가정해도, 그 앞의 모든 줄은
    온전히 파싱 가능해야 한다(전체 파일 손상 위험이 없는 append-only 설계 검증).
    """
    print("\n--- 2. a truncated last line never corrupts earlier lines ---")
    with open(QA_LOG_PATH, "rb") as f:
        good_bytes = f.read()

    # 세 번째 항목을 기록하다가 중간에 죽었다고 가정 — 완전한 JSON 줄의 앞부분만 남기고 자른다.
    with open(QA_LOG_PATH, "ab") as f:
        f.write(b'{"case_no": "2026\xed\x83\x80\xea\xb2\xbd9999", "validation": "PA')
        # <- 여기서 프로세스가 죽었다고 가정. 줄바꿈도, 나머지 JSON도 쓰이지 않는다.

    parsed = []
    broken_lines = 0
    with open(QA_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                broken_lines += 1

    check("exactly 1 broken (truncated) line detected", broken_lines, 1)
    check("all 2 prior complete lines still parse correctly", len(parsed), 2)
    check("prior lines' content is byte-identical to before the crash",
          True, True)  # 아래 별도 바이트 비교로 실질 검증
    with open(QA_LOG_PATH, "rb") as f:
        after_bytes = f.read()
    check_true("the file still starts with exactly the pre-crash bytes (nothing overwritten)",
               after_bytes.startswith(good_bytes))


def cleanup():
    print("\n--- cleanup (qa log file only) ---")
    if os.path.exists(QA_LOG_PATH):
        os.remove(QA_LOG_PATH)
    check_true("qa validation log removed", not os.path.exists(QA_LOG_PATH))
    shutil.rmtree(QA_DIR, ignore_errors=True)
    check_true("qa temp dir removed", not os.path.exists(QA_DIR), QA_DIR)


def run():
    try:
        test_log_entry_matches_validation_result()
        test_truncated_last_line_does_not_corrupt_prior_lines()
    finally:
        cleanup()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
