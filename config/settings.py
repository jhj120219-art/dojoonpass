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

# 우선순위 재계산(01:50) 관련
PRIORITY_REFRESH_TIME: str = "01:50"
