from dataclasses import dataclass

MAX_ITEMS: int = 10
MAX_RETRY: int = 3

# 2026-08-16 Sprint 136 정리: PAGE_LOAD_TIMEOUT/ELEMENT_TIMEOUT/AJAX_TIMEOUT도
# 바로 위 MAX_DOC_RETRY/RETRY_INTERVAL_MINUTES와 같은 모양으로 죽은 중복이었다 —
# `crawler/base_crawler.py`가 이미 이 파일에서 `random_delay`/`CourtInfo`/`MAX_ITEMS`를
# import하면서도 타임아웃 세 값(값도 여기와 동일: 30/20/30)만은 자기 안에 따로
# 선언해 쓰고 있었다(grep 확인, 이쪽 사본은 어디서도 import되지 않음). 실제
# 타임아웃 정책은 `crawler/base_crawler.py`의 것 하나로 통일한다.

import random
def random_delay() -> float:
    return random.uniform(1.5, 4.0)

@dataclass
class CourtInfo:
    code: str
    name: str
    region: str

COURTS = [
    CourtInfo(code="B000210", name="서울중앙지방법원", region="서울"),
    CourtInfo(code="B000201", name="서울동부지방법원", region="서울"),
    CourtInfo(code="B000202", name="서울서부지방법원", region="서울"),
    CourtInfo(code="B000203", name="서울남부지방법원", region="서울"),
    CourtInfo(code="B000204", name="서울북부지방법원", region="서울"),
]

SIDO_LIST = [
    "서울", "경기", "인천", "부산", "대구",
    "광주", "대전", "울산", "세종", "강원",
    "충북", "충남", "전북", "전남", "경북",
    "경남", "제주"
]

# ===== 02:00 PDF 수집 Worker 관련 설정 =====

# 2026-08-17 Sprint 144: 'image'(물건 사진) 추가.
# 주의 — 이 상수는 **실제 적재에 쓰이지 않는다.** `storage/database.py:enqueue_documents()`가
# 자기 안에 같은 목록을 튜플로 들고 있고 그쪽이 실동작 경로다(grep 확인: 이 이름을
# import하는 곳이 없다). 둘 중 하나만 고치면 조용히 어긋나므로 함께 맞춰 둔다.
# 어느 한쪽으로 합치는 것은 `test_schema_hygiene.py`가 소스 텍스트를 직접 대조하는
# 방식과 얽혀 있어 별도 정리 과제로 둔다(docs/SPRINT144_ASSET_PIPELINE.md 참고).
DOC_TYPE_LIST = ["spec", "status", "appraisal", "image"]

# 매각물건명세서/감정평가서는 물건번호가 뒤에 붙는다(`..._btn_aeeWevl2`).
# 현황조사서는 **번호가 붙지 않는다** — 아래 함수의 주석 참고(2026-08-17 DOM 실측).
_BASE_BTN_ID = {
    "spec": "mf_wfm_mainFrame_btn_dspslGdsSpcfc",
    "status": "mf_wfm_mainFrame_btn_curstExmndcTop",
    "appraisal": "mf_wfm_mainFrame_btn_aeeWevl",
}

# 상세페이지에 **수집 버튼이 존재하는** 문서 종류. `_BASE_BTN_ID` 에서 유도한다
# (목록을 두 번 적지 않는다).
#
# 왜 필요한가 (2026-09-04) — `get_doc_button_id()` 가 None 을 돌려주는 이유가
# **두 가지**인데 호출부가 그것을 구별할 방법이 없었다:
#
#     (a) 이 종류의 버튼 id 를 아직 모른다        -> "수집 불가" 로 다룰 만하다
#     (b) 이 종류에는 버튼이라는 개념이 아예 없다  -> 이 함수의 소관이 아니다
#
# 사진(image)이 (b)다 — 캐러셀에서 긁어오지 버튼을 누르지 않는다. 그런데
# `repair_unsupported_status_docs.py` 가 둘을 같게 보고 사진을 "수집 버튼이 없는
# 문서" 로 분류해 FAILED 로 바꾸려 했다(실측 12행, 그중 NO_IMAGE 3행).
# 그 구별을 여기서 이름 있는 값으로 내보낸다.
DOC_BUTTON_DOC_TYPES = frozenset(_BASE_BTN_ID)


def get_doc_button_id(doc_type: str, item_no: str) -> str:
    """문서 종류 + 물건번호(item_no) -> 상세페이지의 수집 버튼 id. 모르면 None.

    ## 현황조사서(status)는 물건번호와 무관하다 (2026-08-17 Sprint 144+ DOM 실측으로 확정)

    예전에는 `item_no != '1'`이면 **None을 돌려 "미지원"으로 처리**했다. 그 판단의 근거는
    "물건번호가 2 이상일 때의 버튼 id가 DOM 분석으로 확인된 적이 없다"였고,
    추측으로 셀렉터를 만들지 않는다는 방침에 따른 **의도적인 보수적 선택**이었다
    (`repair_unsupported_status_docs.py`가 그 한계를 문서화하면서 "나중에 버튼 id가
    확보되면 대상이 저절로 줄어든다"고 후속 조치까지 적어 두었다).

    이제 실제로 확인했다. 실 브라우저로 물건번호 2인 상세페이지 **2건**을 열어 DOM을
    직접 덤프했다(서울중앙 2025타경311 물건2, 2023타경2726 물건2):

        mf_wfm_mainFrame_btn_dspslGdsSpcfc1   매각물건명세서   (물건1)
        mf_wfm_mainFrame_btn_dspslGdsSpcfc2   매각물건명세서   (물건2)
        mf_wfm_mainFrame_btn_aeeWevl1         감정평가서       (물건1)
        mf_wfm_mainFrame_btn_aeeWevl2         감정평가서       (물건2)
        mf_wfm_mainFrame_btn_curstExmndcTop   현황조사서       <- 번호 없음, 단 하나
                                                                 (물건2 페이지에서도 표시됨)

    **번호가 붙은 변형(`...Top2` 등)은 존재하지 않는다.** 명세서·평가서만 번호가 붙고
    현황조사서만 안 붙는다는 것 자체가 "이 문서는 물건 단위가 아니다"라는 신호다.

    내용으로도 확인했다. 물건2 페이지에서 그 버튼을 눌러 오버레이를 읽으니 **한 문서가
    사건의 모든 물건을 담고 있었다** — 부동산임대차정보 표에 번호 1(지2층비201호)과
    번호 2(2층202호)가 나란히 들어 있다. 현황조사서는 집행관이 **사건 단위**로 작성하는
    문서다.

    즉 예전 동작은 "안전한 미지원"이 아니라 **틀린 전제**였다. 그 대가가 컸다 —
    2026-08-17 실측으로 `auction_item` 1,876건 중 물건번호가 1이 아닌 것이 **629건(33.5%)**
    이고, 그 전부가 현황조사서를 **영원히** 받을 수 없는 상태였다(이미 물건1이 같은
    문서를 갖고 있는데도).

    이제 물건번호와 무관하게 같은 버튼 id를 돌려준다. 추측이 아니라 실측이다.
    """
    item_no = (item_no or "1").strip()

    if doc_type == "status":
        # 물건번호를 붙이지 않는다 — 사건 단위 문서이고 버튼도 하나뿐이다.
        return _BASE_BTN_ID["status"]

    if doc_type in ("spec", "appraisal"):
        return _BASE_BTN_ID[doc_type] + item_no

    return None


# 2026-08-16 Sprint 136 정리: 문서 수집 재시도 정책(MAX_DOC_RETRY/RETRY_INTERVAL_MINUTES)이
# 여기 한 번, `storage/database.py`에 또 한 번(값도 같게, 3/30) 따로 선언돼 있었다 — grep
# 확인 결과 실제로 쓰이는 것은 `storage/database.py`의 것뿐이고(`mark_queue_failed()`/
# `claim_next_queue_item()`이 그 모듈 안의 값을 직접 참조), 여기 있던 사본은 어디서도
# import되지 않는 죽은 중복이었다. 두 값이 지금은 우연히 같아 드러나지 않았지만, 한쪽만
# 바꾸면 조용히 어긋날 수 있는 구조라 여기서 지웠다 — 실제 정책 값은
# `storage/database.py:MAX_DOC_RETRY`/`RETRY_INTERVAL_MINUTES` 하나로 통일한다.
# (그쪽을 여기서 import하는 방향으로 합치지 않은 이유: `test_pipeline_integrity.py`가
# `storage/database.py`의 소스 텍스트에서 `MAX_DOC_RETRY\s*=\s*(\d+)` 리터럴 할당을 직접
# 정규식으로 읽어 "테스트에 값을 복제하지 않는다"는 목적을 지키고 있다 — import 문으로
# 바꾸면 그 검사가 깨진다. 안전한 쪽은 실제로 안 쓰이는 이 사본을 지우는 것이었다.)

# Worker 종료 시각 (HH:MM, 24시간제)
DOC_WORKER_END_TIME: str = "04:00"

# Worker 시작 시각. 실행 창 길이를 계산하려면 시작도 알아야 한다
# (예약 작업 등록 시각과 같아야 한다 — register_scheduler_tasks.ps1).
DOC_WORKER_START_TIME: str = "02:00"

# 큐 1행을 실제로 수집하는 데 걸리는 시간(초). **실측값이다.**
# ---------------------------------------------------------------------------
#   브라우저 이동 15.2초 + 수집 약 6.8초  = 약 22초   (2026-08-17 Sprint 146/147 실측)
#   + doc_worker 루프 끝의 time_module.sleep(2)
# 기일이 지난 행은 브라우저를 열지 않고 5.1ms 로 종결되며, `continue` 로 그 sleep 도
# 건너뛴다 — 그래서 적체 2,733행이 13.9초밖에 안 든다(Sprint 146 실측).
#
# 이 값은 `REFRESH_MAX_ITEMS_PER_RUN` 의 안전성을 계산하는 근거다.
# 회귀가 이 상수로 산술을 검증하므로, 실측이 달라지면 여기만 고치면 된다.
DOC_COLLECT_SECONDS_PER_ROW: float = 24.0

# 우선순위 재계산(01:50) 관련
PRIORITY_REFRESH_TIME: str = "01:50"
