"""
crawler/court_crawler.py의 체크포인트 재개(resume_start_idx) 순수 로직 회귀 테스트.

Selenium/실제 브라우저는 전혀 쓰지 않는다 — crawl_court() 안에 인라인으로만 있던 재개 인덱스
계산 로직을 2026-08-10 Sprint 43에서 resume_start_idx()라는 순수 함수로 분리했고(동작은
그대로 유지, 리팩터), 이 파일은 그 계산이 실제로 옳은지 검증한다.

배경: storage/checkpoint.py의 원자적 저장(Sprint 42, docs/BUGS.md #23)은 "체크포인트
파일이 손상되지 않는가"만 보장한다 — "체크포인트 값을 가지고 실제로 올바른 위치부터
재개하는가"는 별도로 검증된 적이 없었다. 이 파일이 그 공백을 메운다.

    python test_crawl_resume.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler.court_crawler import resume_start_idx

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


LIST_ITEMS = [
    {"case_no": "2026타경1000"},
    {"case_no": "2026타경1001"},
    {"case_no": "2026타경1002 / 2026타경1003"},  # 한 물건에 사건번호가 여럿인 경우
    {"case_no": "2026타경1004"},
]


def test_no_checkpoint_starts_at_zero():
    print("\n--- 1. no checkpoint -> start at 0 ---")
    check("resume_from=None", resume_start_idx(LIST_ITEMS, None), 0)
    check("resume_from='' (falsy)", resume_start_idx(LIST_ITEMS, ""), 0)


def test_checkpoint_match_resumes_after_the_completed_item():
    print("\n--- 2. checkpoint matches an item -> resume right after it ---")
    check("match at index 0 -> resume at 1", resume_start_idx(LIST_ITEMS, "2026타경1000"), 1)
    check("match at index 1 -> resume at 2", resume_start_idx(LIST_ITEMS, "2026타경1001"), 2)
    check("match at last index -> resume at len(list)",
          resume_start_idx(LIST_ITEMS, "2026타경1004"), len(LIST_ITEMS))


def test_checkpoint_matches_either_case_no_in_a_joined_entry():
    """한 물건이 사건번호 여러 개를 " / "로 묶어 갖고 있을 때(court_crawler.py의
    실제 데이터 형태), 그 중 어느 사건번호로 체크포인트가 저장돼 있어도 그 항목
    전체를 "완료됨"으로 보고 그 다음 항목부터 재개해야 한다 — crawl_detail()이
    묶인 사건번호 전체를 한 번에 처리하므로 둘 중 하나만 다시 하는 건 의미가 없다.
    """
    print("\n--- 3. joined case_no entry (multiple case numbers, one item) ---")
    check("match via first case_no in the joined entry",
          resume_start_idx(LIST_ITEMS, "2026타경1002"), 3)
    check("match via second case_no in the joined entry",
          resume_start_idx(LIST_ITEMS, "2026타경1003"), 3)


def test_checkpoint_not_in_todays_list_falls_back_to_zero():
    """체크포인트에 저장된 사건이 오늘 목록에 없으면(취하/기각/매각기일 변경 등으로
    더 이상 목록에 없는 경우) 처음부터 다시 훑어야 한다 — 조용히 건너뛰어서
    실제로 있는 항목을 누락시키면 안 된다. 결과가 재크롤링(비효율)이지 데이터
    누락이 아니어야 한다는 게 이 테스트의 핵심이다.
    """
    print("\n--- 4. checkpoint case no longer in today's list -> safe fallback to 0 ---")
    check("stale checkpoint case_no -> falls back to 0 (re-scan everything, no skip)",
          resume_start_idx(LIST_ITEMS, "2026타경9999-없어진사건"), 0)


def test_empty_list_items_returns_zero():
    print("\n--- 5. empty list_items -> 0 (no crash) ---")
    check("empty list with a checkpoint set", resume_start_idx([], "2026타경1000"), 0)
    check("empty list with no checkpoint", resume_start_idx([], None), 0)


def run():
    test_no_checkpoint_starts_at_zero()
    test_checkpoint_match_resumes_after_the_completed_item()
    test_checkpoint_matches_either_case_no_in_a_joined_entry()
    test_checkpoint_not_in_todays_list_falls_back_to_zero()
    test_empty_list_items_returns_zero()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
