"""
체크포인트 재개 위치 계산 (순수 로직, 외부 의존성 없음).

원래 `crawler/court_crawler.py`에 있었으나, 그 모듈은 `crawler/base_crawler.py`를 통해
selenium을 import한다. 그래서 **순수 계산 함수 하나를 쓰려는 회귀 테스트까지** selenium
설치를 강요받았고, selenium이 없는 환경에서 `test_crawl_resume.py`가 ModuleNotFoundError로
아예 실행되지 못했다(2026-08-10 Sprint 47, `crawler/doc_paths.py`와 동일한 사유).

`court_crawler.py`는 하위 호환을 위해 이 이름을 그대로 재노출한다.
"""
from typing import List, Optional


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
        if resume_from in it["case_no"]:
            return idx + 1
    return 0
