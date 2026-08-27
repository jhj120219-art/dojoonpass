"""
체크포인트 재개 위치 계산 (순수 로직, 외부 의존성 없음).

원래 `crawler/court_crawler.py`에 있었으나, 그 모듈은 `crawler/base_crawler.py`를 통해
selenium을 import한다. 그래서 **순수 계산 함수 하나를 쓰려는 회귀 테스트까지** selenium
설치를 강요받았고, selenium이 없는 환경에서 `test_crawl_resume.py`가 ModuleNotFoundError로
아예 실행되지 못했다(2026-08-10 Sprint 47, `crawler/doc_paths.py`와 동일한 사유).

`court_crawler.py`는 하위 호환을 위해 이 이름을 그대로 재노출한다.
"""
from typing import List, Optional


def case_no_matches_list_entry(target_case_no: str, list_entry_case_no: str) -> bool:
    """`target_case_no`가 목록 항목의 `case_no`와 정확히 일치하는지 판정한다.

    목록 항목의 `case_no`는 단일 사건번호이거나(예: "2024타경1009") base_crawler.py의
    `" / ".join(case_nos)`로 묶인 여러 사건번호(예: "2024타경1002 / 2024타경1003",
    한 물건에 사건번호가 여럿인 경우)일 수 있다. 묶인 경우 구성요소 각각과 정확히
    비교한다 — **부분 문자열 포함(`in`)으로 비교하지 않는다.**

    2026-08-15 Sprint 121 신설. 이전에는 `resume_start_idx()`(재개 위치 계산)와
    `base_crawler.go_to_case_detail()`(사건 매칭)가 각자 `X in case_no`(부분 문자열
    포함)를 따로 구현하고 있었다 — 짧은 사건번호가 완전히 무관한 다른 사건번호의
    접두 부분 문자열이기만 해도 걸리는 결함을 **두 곳에 각각** 갖고 있었다는 뜻이다
    (실 DB 실측: "2024타경1009"가 "2024타경100920"의 부분 문자열, 서로 다른 진짜
    사건). validator/validation_engine.py 상단 주석이 남긴 것과 같은 교훈 —
    "같은 판정을 하는 함수가 두 벌이면 한쪽만 고쳐질 수 있다" — 이라 한 곳으로 합친다.

    ## ★ 2026-08-28 (docs/BUGS.md #265) — **한쪽만 쪼개고 있었다**

    Sprint 121 판본은 **목록 쪽만** `" / "` 로 쪼갰다:

        return target_case_no in [c.strip() for c in list_entry_case_no.split(" / ")]

    그래서 **찾는 쪽이 병합 사건번호이면 자기 자신과도 일치하지 않는다.**

        m("2023타경300780",                      "2023타경300780 / 2023타경302427")  -> True
        m("2023타경300780 / 2023타경302427",     "2023타경300780 / 2023타경302427")  -> **False**  <- 같은 문자열인데
        m("2023타경300780 / 2023타경302427",     "2023타경300780")                   -> **False**
        m("2023타경302427 / 2023타경300780",     "2023타경300780 / 2023타경302427")  -> **False**  <- 순서만 달라도

    큐/`auction` 에는 병합 사건번호가 그대로 **저장된다**(한 물건에 사건번호가 여럿인
    경우 `base_crawler` 가 `" / ".join(case_nos)` 로 만든 값이 그대로 흘러온다).
    즉 찾는 쪽이 병합인 경우가 예외가 아니라 **일상**이다. 실측(2026-08-28 운영 DB):

        document_queue 병합 사건번호 행   1,507
          그중 pending 222 / failed 105 / refresh 4 = **331행이 현재 진행형**
        auction 병합 사건번호 행            602

    그 331행은 **매일 밤 반드시 매칭에 실패한다.** 실패 한 번이 상세페이지 이동
    1회(실측 중앙값 10.9초)를 태우고 재시도 예산을 깎는다. 2026-08-28 워커 로그에서
    `사건 매칭 실패` 경고가 67건 났고 그날 `failed` 가 95 -> 205 로 늘었다.

    ## 고친 방법 — **양쪽을 쪼개고 구성요소가 겹치는지** 본다

    한 물건의 사건번호 묶음은 시점에 따라 표기가 달라질 수 있다(병합이 생기거나
    풀리거나, 순서가 바뀌거나). 어느 쪽이든 **구성요소를 하나라도 공유하면 같은 물건**이다 —
    사건번호는 법원 안에서 유일하고, 병합 표기는 같은 경매를 가리키기 때문이다.

    ★ Sprint 121 이 막은 것(부분 문자열 포함)은 **그대로 막힌다.** 비교는 여전히
      구성요소끼리의 **정확 일치**다 — `"2024타경1009"` 는 `"2024타경100920"` 과
      다른 문자열이므로 겹치지 않는다.

    ★ 빈 문자열은 **아무것도 일치시키지 않는다.** 예전 판본은 `m("", "")` 가 True 였다
      (`"" in [""]`). 사건번호가 비었다는 것은 "모른다"는 뜻이지 "아무거나 맞다"가
      아니다 — 그 상태로 첫 항목에 진입하면 **엉뚱한 물건의 자산을 저장**할 수 있고,
      그것이 `go_to_case_detail()` 이 `require_exact_item` 으로 막으려는 바로 그 사고다.
    """
    target = _case_no_parts(target_case_no)
    entry = _case_no_parts(list_entry_case_no)
    return bool(target & entry)


def _case_no_parts(case_no: str) -> set:
    """`"A / B"` -> `{"A", "B"}`. 비어 있으면 빈 집합(= 아무것도 일치하지 않는다)."""
    return {part.strip() for part in (case_no or "").split(" / ") if part.strip()}


def resume_start_idx(list_items: List[dict], resume_from: Optional[str]) -> int:
    """체크포인트(resume_from=마지막으로 완료한 case_no)를 기준으로 오늘자 목록
    (list_items)에서 이어서 시작할 인덱스를 계산한다(2026-08-10 Sprint 43 —
    crawl_court() 안에 인라인으로만 있던 재개 로직을 순수 함수로 분리해 Selenium 없이
    회귀 테스트할 수 있게 함, 동작은 그대로 유지).

    resume_from이 오늘 목록에 없으면(취하/기각/매각기일 변경 등으로 그 사건이 더 이상
    목록에 없는 경우) 0을 반환해 처음부터 다시 훑는다 — 데이터 손상은 아니고(upsert_batch가
    같은 사건을 다시 수집해도 멱등하게 갱신할 뿐) 이미 끝낸 항목을 다시 도는 비효율만
    생긴다. 이 함수는 그 fallback이 실제로 "0부터 안전하게 다시 시작"으로 동작하는지,
    정상 매칭 시 정확히 "그 다음 항목"부터 시작하는지를 검증 대상으로 삼는다.
    """
    if not resume_from:
        return 0
    for idx, it in enumerate(list_items):
        if case_no_matches_list_entry(resume_from, it["case_no"]):
            return idx + 1
    return 0
