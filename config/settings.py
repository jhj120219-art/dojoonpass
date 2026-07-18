from dataclasses import dataclass

MAX_ITEMS: int = 10
MAX_RETRY: int = 3
PAGE_LOAD_TIMEOUT: int = 30
ELEMENT_TIMEOUT: int = 20
AJAX_TIMEOUT: int = 30

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

DOC_TYPE_LIST = ["spec", "status", "appraisal"]

# item_no=1일 때의 버튼 id (매각물건명세서/감정평가서는 item_no별로 규칙적으로
# 숫자가 붙는 것을 확인했으나, 현황조사서는 item_no=1(Top)만 확인된 상태다.
_BASE_BTN_ID = {
    "spec": "mf_wfm_mainFrame_btn_dspslGdsSpcfc",
    "status": "mf_wfm_mainFrame_btn_curstExmndcTop",
    "appraisal": "mf_wfm_mainFrame_btn_aeeWevl",
}


def get_doc_button_id(doc_type: str, item_no: str) -> str:
    """
    문서 종류 + 물건번호(item_no) -> 버튼 id.
    현황조사서는 item_no=1 이외의 버튼 id가 DOM 분석으로 확인된 적이 없으므로,
    item_no != '1' 이면 None을 반환해 명시적으로 "미지원"을 알린다.
    (추측으로 셀렉터를 만들지 않는다 - 잘못된 id로 엉뚱한 버튼을 누르는 것을 방지)
    """
    item_no = (item_no or "1").strip()

    if doc_type == "status":
        return _BASE_BTN_ID["status"] if item_no == "1" else None

    if doc_type in ("spec", "appraisal"):
        return _BASE_BTN_ID[doc_type] + item_no

    return None


# 재시도 정책
MAX_DOC_RETRY: int = 3
RETRY_INTERVAL_MINUTES: int = 30

# Worker 종료 시각 (HH:MM, 24시간제)
DOC_WORKER_END_TIME: str = "04:00"

# 우선순위 재계산(01:50) 관련
PRIORITY_REFRESH_TIME: str = "01:50"
