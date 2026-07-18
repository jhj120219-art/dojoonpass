import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import hashlib
import logging
import glob
from datetime import datetime
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from storage.database import get_connection
from config.settings import random_delay

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/doc_collect.log", encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

BASE_STORAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "docs")

DOC_BUTTONS = {
    "SPEC":     "mf_wfm_mainFrame_btn_dspslGdsSpcfc1",
    "STATUS":   "mf_wfm_mainFrame_btn_curstExmndcTop",
    "APPRAISAL":"mf_wfm_mainFrame_btn_aeeWevl1",
}

def build_driver(download_dir: str) -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
    }
    opts.add_experimental_option("prefs", prefs)
    svc = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=svc, options=opts)
    driver.set_page_load_timeout(30)
    return driver

def wait_loading(driver):
    try:
        WebDriverWait(driver, 30).until(
            EC.invisibility_of_element_located((By.ID, "__processbarIFrame"))
        )
    except:
        pass
    time.sleep(random_delay())

def select_court(driver, court_name: str) -> bool:
    try:
        sel_el = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "mf_wfm_mainFrame_sbx_auctnCsSrchCortOfc"))
        )
        time.sleep(1)
        driver.execute_script("arguments[0].value = arguments[1];", sel_el, court_name)
        driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", sel_el)
        time.sleep(0.5)
        return True
    except Exception as e:
        logger.warning("법원 선택 실패: %s", str(e))
        return False

def go_to_detail(driver, court_name: str, case_no: str, item_no: str) -> bool:
    try:
        # 사건번호 직접 검색으로 상세페이지 진입
        first_case_no = case_no.split(" / ")[0].strip()
        search_url = (
            "https://www.courtauction.go.kr/pgj/index.on"
            "?w2xPath=/pgj/ui/pgj100/PGJ159M00.xml"
        )
        driver.get(search_url)
        time.sleep(5)

        # 법원 선택
        if not select_court(driver, court_name):
            return False

        # 사건번호 입력
        import re
        m = re.match(r"(\d{4})타경(\d+)", first_case_no)
        if not m:
            return False

        year = m.group(1)
        number = m.group(2)

        try:
            # 연도 select (JS로 직접 설정)
            year_sel = driver.find_element(By.ID, "mf_wfm_mainFrame_sbx_auctnCsSrchCsYear")
            driver.execute_script("arguments[0].value = arguments[1];", year_sel, year)
            driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", year_sel)
            time.sleep(0.5)
            # 사건번호 input
            num_el = driver.find_element(By.ID, "mf_wfm_mainFrame_ibx_auctnCsSrchCsNo")
            num_el.clear()
            num_el.send_keys(number)
        except Exception as e:
            logger.warning("사건번호 입력 실패: %s", str(e))
            return False

        # 검색
        driver.find_element(By.ID, "mf_wfm_mainFrame_btn_auctnCsSrchBtn").click()
        wait_loading(driver)

        # 결과에서 물건번호 클릭
        import re as re2
        dtlpage_pat = re2.compile(r"moveDtlPage\((\d+)\)")
        rows = driver.find_elements(By.XPATH, "//table//tr")
        target_idx = None
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            for cell in cells:
                if item_no in (cell.text or ""):
                    links_in_row = row.find_elements(By.XPATH,
                        ".//a[contains(@onclick,'moveDtlPage')]")
                    for a in links_in_row:
                        mm = dtlpage_pat.search(a.get_attribute("onclick") or "")
                        if mm:
                            target_idx = int(mm.group(1))
                            break
            if target_idx is not None:
                break

        # target_idx 못 찾으면 첫번째 링크로
        if target_idx is None:
            all_links = driver.find_elements(By.XPATH,
                "//a[contains(@onclick,'moveDtlPage')]")
            if all_links:
                mm = dtlpage_pat.search(all_links[0].get_attribute("onclick") or "")
                if mm:
                    target_idx = int(mm.group(1))

        if target_idx is None:
            return False

        driver.execute_script(f"moveDtlPage({target_idx})")
        time.sleep(5)

        body = driver.execute_script("return document.body.innerText;") or ""
        return "물건기본정보" in body

    except Exception as e:
        logger.warning("상세페이지 진입 실패: %s", str(e))
        return False

def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def download_doc(driver, doc_type: str, item_id: int) -> Optional[str]:
    btn_id = DOC_BUTTONS[doc_type]
    save_dir = os.path.join(BASE_STORAGE, doc_type)
    os.makedirs(save_dir, exist_ok=True)

    before = set(glob.glob(save_dir + "\\*"))
    main_handle = driver.current_window_handle

    try:
        btn = driver.find_element(By.ID, btn_id)
        driver.execute_script("arguments[0].click();", btn)

        # 팝업/새탭 대기 (최대 10초)
        new_handle = None
        for _ in range(20):
            time.sleep(0.5)
            handles = [h for h in driver.window_handles if h != main_handle]
            if handles:
                new_handle = handles[0]
                break

        if not new_handle:
            return None

        driver.switch_to.window(new_handle)
        time.sleep(4)

        # 저장 버튼
        try:
            save_btn = driver.find_element(By.ID, "mf_btn_save")
            driver.execute_script("arguments[0].click();", save_btn)
            time.sleep(8)
        except:
            pass

        after = set(glob.glob(save_dir + "\\*"))
        new_files = [f for f in (after - before) if f.lower().endswith(".pdf")]

        driver.close()
        driver.switch_to.window(main_handle)

        return new_files[0] if new_files else None

    except Exception as e:
        logger.warning("download_doc 실패 [%s]: %s", doc_type, str(e))
        try:
            driver.switch_to.window(main_handle)
        except:
            pass
        return None

def save_doc_raw(conn, item_id: int, doc_type: str, pdf_path: str) -> bool:
    try:
        size = os.path.getsize(pdf_path)
        fhash = file_hash(pdf_path)
        now = datetime.now().isoformat()

        # 버전 계산
        existing = conn.execute(
            "SELECT MAX(doc_version) as v FROM doc_raw WHERE item_id=? AND doc_type=?",
            (item_id, doc_type)
        ).fetchone()
        version = (existing["v"] or 0) + 1

        import pdfplumber
        try:
            with pdfplumber.open(pdf_path) as pdf:
                page_count = len(pdf.pages)
        except:
            page_count = 0

        conn.execute("""
            INSERT OR IGNORE INTO doc_raw
            (item_id, doc_type, storage_path, file_hash, file_size,
             doc_version, page_count, crawl_date, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (item_id, doc_type, pdf_path, fhash, size,
              version, page_count, datetime.today().strftime("%Y-%m-%d"), now))

        conn.execute("""
            INSERT OR REPLACE INTO document_status
            (item_id, doc_type, status, updated_at)
            VALUES (?, ?, 'READY', ?)
        """, (item_id, doc_type, now))

        conn.commit()
        return True
    except Exception as e:
        logger.warning("save_doc_raw 실패: %s", str(e))
        return False

def save_failure(conn, item_id: int, doc_type: str, error: str):
    now = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO document_collect_failures (item_id, doc_type, error_message, created_at)
        VALUES (?,?,?,?)
    """, (item_id, doc_type, error[:500], now))
    conn.execute("""
        INSERT OR REPLACE INTO document_status
        (item_id, doc_type, status, updated_at)
        VALUES (?, ?, 'FAILED', ?)
    """, (item_id, doc_type, now))
    conn.commit()

def collect_all(limit: int = 10):
    conn = get_connection()
    try:
        # COLLECTING 상태 중 미수집 item 조회
        items = conn.execute("""
            SELECT DISTINCT ai.id, ai.case_no, ai.item_no, ai.court_name
            FROM auction_item ai
            JOIN document_status ds ON ai.id = ds.item_id
            WHERE ds.status = 'COLLECTING'
            LIMIT ?
        """, (limit,)).fetchall()

        logger.info("수집 대상: %d건", len(items))

        for item in items:
            item_id = item["id"]
            case_no = item["case_no"]
            item_no = item["item_no"]
            court_name = item["court_name"]

            logger.info("[%s / 물건%s] %s 수집 시작", case_no, item_no, court_name)

            # doc_type별 미수집 확인
            pending_docs = conn.execute("""
                SELECT doc_type FROM document_status
                WHERE item_id = ? AND status = 'COLLECTING'
            """, (item_id,)).fetchall()
            pending_types = [d["doc_type"] for d in pending_docs]

            if not pending_types:
                continue

            driver = build_driver(os.path.join(BASE_STORAGE, "SPEC"))
            try:
                ok = go_to_detail(driver, court_name, case_no, item_no)
                logger.info("[%s] go_to_detail=%s", case_no, ok)
                if not ok:
                    for doc_type in pending_types:
                        save_failure(conn, item_id, doc_type, "상세페이지 진입 실패")
                    continue

                for doc_type in pending_types:
                    logger.info("  [%s] 다운로드 시도...", doc_type)
                    # download_dir 변경
                    save_dir = os.path.join(BASE_STORAGE, doc_type)
                    os.makedirs(save_dir, exist_ok=True)

                    pdf_path = download_doc(driver, doc_type, item_id)
                    if pdf_path:
                        ok2 = save_doc_raw(conn, item_id, doc_type, pdf_path)
                        if ok2:
                            logger.info("  [%s] 저장 완료: %s", doc_type, pdf_path)
                        else:
                            save_failure(conn, item_id, doc_type, "DB 저장 실패")
                    else:
                        save_failure(conn, item_id, doc_type, "다운로드 실패")

                    time.sleep(random_delay())

            finally:
                driver.quit()
                logger.info("[%s] 브라우저 종료", case_no)

    finally:
        conn.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="수집할 물건 수")
    args = parser.parse_args()
    logger.info("===== 문서 수집 시작 (limit=%d) =====", args.limit)
    collect_all(limit=args.limit)
    logger.info("===== 문서 수집 완료 =====")
