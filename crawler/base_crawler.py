import time
import re
import logging
from typing import Optional, List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from config.settings import random_delay, CourtInfo, MAX_ITEMS
from crawler.resume import case_no_matches_list_entry

logger = logging.getLogger(__name__)

PAGE_LOAD_TIMEOUT = 30
ELEMENT_TIMEOUT = 20
AJAX_TIMEOUT = 30
COURT_SELECT_ID = "mf_wfm_mainFrame_sbx_rletDxdyCortOfc"

def build_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    svc = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=svc, options=opts)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver

def restart_driver(driver: Optional[webdriver.Chrome]) -> webdriver.Chrome:
    logger.warning("드라이버 재시작 중...")
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    time.sleep(2)
    new_driver = build_driver()
    logger.info("드라이버 재시작 완료")
    return new_driver

def wait_loading(driver: webdriver.Chrome) -> None:
    try:
        WebDriverWait(driver, AJAX_TIMEOUT).until(
            EC.invisibility_of_element_located((By.ID, "__processbarIFrame"))
        )
    except Exception:
        pass
    time.sleep(random_delay())

def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def select_court(driver: webdriver.Chrome, court: CourtInfo) -> bool:
    try:
        sel_el = WebDriverWait(driver, ELEMENT_TIMEOUT).until(
            EC.presence_of_element_located((By.ID, COURT_SELECT_ID))
        )
        time.sleep(1)
        driver.execute_script("arguments[0].value = arguments[1];", sel_el, court.code)
        driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", sel_el)
        time.sleep(0.5)
        selected = driver.execute_script("return arguments[0].value;", sel_el)
        logger.info("법원 선택: %s (실제값: %s)", court.name, selected)
        return True
    except Exception as e:
        logger.error("법원 선택 실패 [%s]: %s", court.name, str(e))
        return False

def go_to_schedule(driver: webdriver.Chrome, court: CourtInfo) -> Tuple[bool, bool]:
    try:
        driver.get(
            "https://www.courtauction.go.kr/pgj/index.on"
            "?w2xPath=/pgj/ui/pgj100/PGJ153F00.xml"
        )
        time.sleep(5)

        if not select_court(driver, court):
            return False, False

        driver.find_element(By.ID, "mf_wfm_mainFrame_btn_rletSrch").click()
        wait_loading(driver)

        schedule_links = driver.find_elements(By.XPATH,
            "//a[@onclick and contains(@onclick,'moveDtlUrl')]")

        if not schedule_links:
            logger.info("[%s] 오늘 매각기일 없음. 스킵.", court.name)
            return True, False

        driver.execute_script("arguments[0].click();", schedule_links[0])
        wait_loading(driver)

        WebDriverWait(driver, ELEMENT_TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH,
                "//a[@onclick and contains(@onclick,'moveDtlPage')]"))
        )
        time.sleep(1)
        return True, True

    except Exception as e:
        logger.error("go_to_schedule failed [%s]: %s", court.name, str(e))
        return False, False

def go_to_list(driver: webdriver.Chrome, court: CourtInfo) -> bool:
    try:
        driver.get(
            "https://www.courtauction.go.kr/pgj/index.on"
            "?w2xPath=/pgj/ui/pgj100/PGJ153F00.xml"
        )
        time.sleep(5)

        if not select_court(driver, court):
            raise Exception("법원 선택 실패: " + court.name)

        driver.find_element(By.ID, "mf_wfm_mainFrame_btn_rletSrch").click()
        wait_loading(driver)

        first_link = WebDriverWait(driver, ELEMENT_TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH,
                "//a[@onclick and contains(@onclick,'moveDtlUrl')]"))
        )
        driver.execute_script("arguments[0].click();", first_link)
        wait_loading(driver)

        WebDriverWait(driver, ELEMENT_TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH,
                "//a[@onclick and contains(@onclick,'moveDtlPage')]"))
        )
        time.sleep(1)
        return True
    except Exception as e:
        logger.error("go_to_list failed [%s]: %s", court.name, str(e))
        return False

def wait_for_detail(driver: webdriver.Chrome, expected_case_no: str) -> bool:
    """
    사건번호가 여러 개인 경우(예: '2020타경1013 / 2020타경2856')
    그 중 하나라도 페이지에 나타나면 성공으로 판단
    """
    case_pat = re.compile(r"\d{4}타경\d+")
    expected_nos = set(case_pat.findall(expected_case_no))

    if not expected_nos:
        for _ in range(40):
            try:
                text = driver.execute_script("return document.body.innerText;") or ""
                has_list = bool(driver.find_elements(By.XPATH,
                    "//a[@onclick and contains(@onclick,'moveDtlPage(0)')]"))
                if "물건기본정보" in text and not has_list:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    for _ in range(40):
        try:
            text = driver.execute_script("return document.body.innerText;") or ""
            found = set(case_pat.findall(text))
            has_list = bool(driver.find_elements(By.XPATH,
                "//a[@onclick and contains(@onclick,'moveDtlPage(0)')]"))
            if (found & expected_nos) and not has_list and "물건기본정보" in text:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

def parse_basic_info(driver: webdriver.Chrome) -> dict:
    result: dict = {}
    try:
        rows = driver.find_elements(By.XPATH, "//table//tr")
        for row in rows:
            ths = row.find_elements(By.TAG_NAME, "th")
            tds = row.find_elements(By.TAG_NAME, "td")
            for i, th in enumerate(ths):
                key = clean(th.text)
                val = clean(tds[i].text) if i < len(tds) else "-"
                if key and val and key not in result:
                    result[key] = val
    except Exception as e:
        logger.warning("parse_basic_info error: %s", str(e))
    return result

def parse_section_table(driver: webdriver.Chrome, h3_keyword: str) -> list:
    records = []
    try:
        rows = driver.find_elements(By.XPATH,
            "//h3[contains(text(),'" + h3_keyword + "')]/following::table[1]//tr")
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if not cells:
                continue
            texts = [clean(c.text) for c in cells]
            if any(texts):
                records.append(texts)
    except Exception as e:
        logger.warning("parse_section_table(%s) error: %s", h3_keyword, str(e))
    return records

def parse_gamjung(driver: webdriver.Chrome) -> str:
    try:
        el = driver.find_element(By.XPATH,
            "//h3[contains(text(),'감정평가요항표')]"
            "/following::*[self::div or self::p or self::ul or self::table][1]")
        return clean(el.text)
    except Exception:
        return ""

def collect_list_items(driver: webdriver.Chrome, max_items: int) -> List[dict]:
    case_pat = re.compile(r"\d{4}타경\d+")
    date_pat = re.compile(r"\d{4}\.\d{2}\.\d{2}")
    dtlpage_pat = re.compile(r"moveDtlPage\((\d+)\)")
    list_items: List[dict] = []

    rows = driver.find_elements(By.XPATH, "//table//tr")
    i = 0
    while i < len(rows) and len(list_items) < max_items:
        cells = rows[i].find_elements(By.TAG_NAME, "td")
        texts = [clean(c.text) for c in cells]
        if len(texts) < 8 or not case_pat.search(texts[1]):
            i += 1
            continue

        dtl_idx = None
        try:
            addr_a = cells[3].find_element(By.XPATH,
                ".//a[contains(@onclick,'moveDtlPage')]")
            m = dtlpage_pat.search(addr_a.get_attribute("onclick") or "")
            if m:
                dtl_idx = int(m.group(1))
        except Exception:
            pass

        case_nos = case_pat.findall(texts[1])
        next_texts: List[str] = []
        if i + 1 < len(rows):
            next_cells = rows[i+1].find_elements(By.TAG_NAME, "td")
            next_texts = [clean(c.text) for c in next_cells]

        status = "-"
        for t in next_texts:
            if any(k in t for k in ["유찰", "진행", "취하", "기각"]):
                status = t
                break

        date_m = date_pat.search(texts[7])
        list_items.append({
            "case_no": " / ".join(case_nos),
            "obj_no": texts[2],
            "addr": texts[3],
            "appraisal": texts[6],
            "date": date_m.group() if date_m else "-",
            "status": status,
            "dtl_idx": dtl_idx,
        })
        i += 2

    return list_items


def go_to_case_detail(driver: webdriver.Chrome, court_code: str, case_no: str) -> bool:
    """
    02:00 PDF 수집 Worker 전용 진입 함수.

    주의: 이 사이트(WebSquare)는 court_code+case_no를 URL 파라미터로 넘겨
    사건 상세로 직접 이동하는 방식을 지원하지 않는다 (Step 2 DOM 분석에서 확인된
    세션/AJAX 기반 렌더링 구조). 따라서 기존 06:00 크롤러와 동일하게
    "법원 선택 -> 기일 목록 진입 -> 목록에서 사건번호 매칭 -> moveDtlPage 호출"
    경로를 그대로 재사용한다.
    """
    from config.courts import ALL_COURTS

    court = next((c for c in ALL_COURTS if c.code == court_code), None)
    if not court:
        logger.error("법원 코드 매칭 실패: %s", court_code)
        return False

    ok, has_schedule = go_to_schedule(driver, court)
    if not ok or not has_schedule:
        logger.warning("[%s] 기일 목록 진입 실패 또는 기일 없음", court.name)
        return False

    list_items = collect_list_items(driver, MAX_ITEMS)
    target = None
    for item in list_items:
        # 2026-08-15 Sprint 121: `case_no in item["case_no"]`(부분 문자열 포함)이던
        # 것을 정확 비교로 고쳤다(crawler/resume.py:case_no_matches_list_entry 참고 —
        # crawler/resume.py의 resume_start_idx()가 같은 결함을 갖고 있었다). 여기서는
        # 부분일치로 엉뚱한 사건에 먼저 걸려도 wait_for_detail()의 정확한 사건번호
        # 대조가 최종 오염은 막아주지만(found & expected_nos, 부분일치 아님), 매번
        # 같은 무관한 항목에 먼저 걸려 타임아웃 후 실패하므로 그 사건의 문서 수집이
        # 재시도해도 계속 실패했다.
        if case_no_matches_list_entry(case_no, item["case_no"]):
            target = item
            break

    if not target or target["dtl_idx"] is None:
        logger.warning("[%s] 사건 매칭 실패: %s", court.name, case_no)
        return False

    driver.execute_script("moveDtlPage(" + str(target["dtl_idx"]) + ")")
    return wait_for_detail(driver, case_no)
