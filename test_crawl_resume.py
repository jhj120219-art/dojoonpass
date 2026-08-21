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

# crawler/resume.py(순수 로직). 예전에는 crawler.court_crawler에서 가져왔는데 그 모듈이
# base_crawler를 통해 selenium을 import하는 탓에 selenium 없는 환경에서 실행 자체가
# 불가능했다(2026-08-10 Sprint 47). 검증 대상 함수는 동일한 그 함수다.
from crawler.resume import resume_start_idx, case_no_matches_list_entry

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


def test_case_no_matches_list_entry_is_exact_not_substring():
    """2026-08-15 Sprint 121 신설. `case_no_matches_list_entry()`는 `resume_start_idx()`와
    `crawler/base_crawler.py:go_to_case_detail()` 둘 다 쓰는 공용 판정 함수다(예전에는
    두 곳이 각자 부분 문자열 `in`으로 따로 구현하고 있었다 — 같은 결함을 두 벌 가진
    상태였다). 이 함수 하나만 검증하면 두 호출부 모두를 커버한다 — `go_to_case_detail()`
    자체는 selenium 의존이라 여기서 직접 실행할 수는 없다.
    """
    print("\n--- 0. case_no_matches_list_entry: 정확 일치 (공용 판정 함수) ---")
    check("단일 사건번호 정확 일치", case_no_matches_list_entry("2024타경1009", "2024타경1009"), True)
    check("묶인 항목의 첫 번째와 일치",
          case_no_matches_list_entry("2024타경1009", "2024타경1009 / 2024타경1010"), True)
    check("묶인 항목의 두 번째와 일치",
          case_no_matches_list_entry("2024타경1010", "2024타경1009 / 2024타경1010"), True)
    check("무관한 사건번호의 부분 문자열이면 일치하지 않는다(실 DB 실측 사례)",
          case_no_matches_list_entry("2024타경1009", "2024타경100920"), False)
    check("역방향(긴 쪽을 찾을 때 짧은 쪽에 안 걸림)",
          case_no_matches_list_entry("2024타경100920", "2024타경1009"), False)


def test_no_checkpoint_starts_at_zero():
    print("\n--- 1. no checkpoint -> start at 0 ---")
    check("resume_from=None", resume_start_idx(LIST_ITEMS, None), 0)
    check("resume_from='' (falsy)", resume_start_idx(LIST_ITEMS, ""), 0)

    # ★ 2026-08-21 Sprint 246: 위 두 줄만으로는 **부족하다.**
    #
    # mutation 으로 확인했다 - `if not resume_from:` 를 `if resume_from is None:` 로
    # 바꿔도 위 검사는 그대로 통과한다(생존). 정상 목록에서는 빈 문자열이 어느 항목과도
    # 일치하지 않아 루프가 끝까지 돌고 결국 같은 0 을 내기 때문이다. 즉 **결과는 같고
    # 경로만 다른** 상태라 위 검사가 두 구현을 구분하지 못한다.
    #
    # 목록에 빈 조각이 섞이면 갈린다. 크롤 목록의 `case_no` 는 " / " 로 이어 붙는데,
    # 뒤가 잘리면 `"2026타경1005 / "` 처럼 되고 split 결과에 **빈 문자열이 들어간다.**
    # 그러면 빈 체크포인트가 그 항목과 "일치"해 `idx + 1` 을 돌려준다 =
    # **첫 물건을 통째로 건너뛴다.** 크롤 누락은 조용하다 - 아무 오류도 안 난다.
    #
    # 실측(2026-08-21): 현행 구현 0 / `is None` 구현 1.
    BLANK_FRAGMENT = [
        {"case_no": "2026타경1005 / "},   # 뒤가 잘려 빈 조각이 생긴 항목
        {"case_no": "2026타경1006"},
    ]
    check("★ 빈 조각이 섞인 목록에서도 resume_from='' 는 처음부터다(물건을 건너뛰지 않는다)",
          resume_start_idx(BLANK_FRAGMENT, ""), 0)
    check("★ 같은 목록에서 resume_from=None 도 처음부터다",
          resume_start_idx(BLANK_FRAGMENT, None), 0)
    # 빈 조각이 정말 생기는지 자체를 고정한다(전제가 사라지면 위 검사가 공허해진다)
    check("전제: '2026타경1005 / ' 는 빈 조각을 만든다",
          "" in [c.strip() for c in "2026타경1005 / ".split(" / ")], True)


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


def test_checkpoint_does_not_match_an_unrelated_case_no_by_prefix():
    """2026-08-15 Sprint 121: 실 DB(auction.db)에서 실제로 재현된 충돌 ―
    "2024타경1009"가 무관한 다른 사건 "2024타경100920"의 부분 문자열이다(둘 다
    같은 법원의 서로 다른 진짜 사건). 예전 구현(`resume_from in it["case_no"]`,
    부분 문자열 포함)은 이런 경우 목록에서 더 먼저 나오는 무관한 사건을
    "체크포인트가 매칭됐다"고 오판해 실제 체크포인트 위치를 건너뛸 수 있었다.

    아래 목록은 그 충돌을 그대로 재현한다 ― 무관한 "...100920"이 진짜 체크포인트
    "...1009"보다 앞에 있다. 부분 문자열로 매칭했다면 idx=0 다음(1)을 반환해
    idx=1(진짜 체크포인트)을 건너뛰었을 것이다.
    """
    print("\n--- 3-B. unrelated case_no sharing a numeric prefix -> no false match ---")
    collision_items = [
        {"case_no": "2024타경100920"},   # 무관한 다른 사건 - "1009"를 포함하지만 다른 사건
        {"case_no": "2024타경1009"},     # 진짜 체크포인트가 가리키는 사건
        {"case_no": "2024타경1010"},
    ]
    check("무관한 접두 사건을 건너뛰고 진짜 사건 바로 다음부터 재개",
          resume_start_idx(collision_items, "2024타경1009"), 2)
    # 짧은 쪽이 체크포인트인데 목록에 없고, 그걸 포함하는 무관한 사건만 있는 경우도
    # 안전하게 "못 찾음"(0부터 다시 훑기)으로 처리돼야 한다 ― 잘못된 항목을 완료로
    # 오인해 건너뛰면 안 된다.
    check("포함 관계만으로는 매칭되지 않고 안전하게 0으로 폴백",
          resume_start_idx([{"case_no": "2024타경100920"}], "2024타경1009"), 0)


def test_empty_list_items_returns_zero():
    print("\n--- 5. empty list_items -> 0 (no crash) ---")
    check("empty list with a checkpoint set", resume_start_idx([], "2026타경1000"), 0)
    check("empty list with no checkpoint", resume_start_idx([], None), 0)


def run():
    test_case_no_matches_list_entry_is_exact_not_substring()
    test_no_checkpoint_starts_at_zero()
    test_checkpoint_match_resumes_after_the_completed_item()
    test_checkpoint_matches_either_case_no_in_a_joined_entry()
    test_checkpoint_does_not_match_an_unrelated_case_no_by_prefix()
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
