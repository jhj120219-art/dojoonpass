import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import glob
import shutil
import hashlib
import logging
import json
from datetime import datetime
from urllib.parse import urljoin
from typing import Optional, Dict
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)

# 경로 규칙은 selenium 없이도 쓸 수 있어야 해서 crawler/doc_paths.py로 분리했다
# (이 모듈은 최상단에서 selenium을 import하므로, 경로 계산만 필요한 쪽까지 selenium
# 설치를 강요하게 된다 — Sprint 47). 아래 재노출로 기존 호출부는 그대로 동작한다.
from crawler.doc_paths import (  # noqa: F401  (하위 호환 재노출)
    PROJECT_ROOT,
    DOWNLOAD_DIR,
    DOCUMENT_ROOT,
    get_doc_dir,
    doc_exists,
    status_overlay_has_data,
    _PRIMARY_EXT,
)

KAPANET_BASE = "https://ca.kapanet.or.kr"
OVERLAY_TIMEOUT = 15
NEW_WINDOW_TIMEOUT = 15


def get_download_driver_options():
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
    }
    opts.add_experimental_option("prefs", prefs)
    return opts


def build_download_driver():
    """
    doc_worker 전용 브라우저 생성 함수.
    base_crawler.build_driver()는 다운로드 경로 설정이 없어서
    Chrome이 PDF를 Windows 기본 다운로드 폴더로 보내버리는 문제가 있었다.
    (wait_for_download가 DOWNLOAD_DIR만 지켜보므로 항상 타임아웃 발생)
    반드시 이 함수로 만든 driver만 doc_worker에서 사용한다.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    opts = get_download_driver_options()
    svc = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=svc, options=opts)
    driver.set_page_load_timeout(30)
    return driver


def restart_download_driver(driver):
    logger.warning("드라이버 재시작 중... (다운로드 설정 유지)")
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    time.sleep(2)
    new_driver = build_download_driver()
    logger.info("드라이버 재시작 완료")
    return new_driver


def calc_file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def wait_for_download(before_files: set, timeout: int = 30) -> Optional[str]:
    """
    window_handle 방식 폐기.
    다운로드 폴더에 새 파일이 생기고, 확장자가 .pdf로 확정되며,
    연속 2회 크기 측정이 동일할 때(=다운로드 완료로 안정화) 성공으로 판단한다.
    """
    elapsed = 0.0
    interval = 1.0
    stable_path = None
    stable_size = -1
    stable_count = 0

    while elapsed < timeout:
        time.sleep(interval)
        elapsed += interval

        after_files = set(glob.glob(DOWNLOAD_DIR + os.sep + "*"))
        new_files = [f for f in (after_files - before_files) if not f.lower().endswith(".crdownload")]
        pdf_files = [f for f in new_files if f.lower().endswith(".pdf")]

        if not pdf_files:
            continue

        candidate = pdf_files[0]
        try:
            size = os.path.getsize(candidate)
        except OSError:
            continue

        if size <= 0:
            continue

        if candidate == stable_path and size == stable_size:
            stable_count += 1
            if stable_count >= 2:
                return candidate
        else:
            stable_path = candidate
            stable_size = size
            stable_count = 0

    return None


def _empty_result() -> Dict:
    return {
        "success": False,
        "storage_type": None,
        "files_saved": [],
        "previous_hash": "",
        "new_hash": "",
        "partial": False,
    }


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# =====================================================================
# SpecCollector (매각물건명세서) - 새 탭 전환 -> 파일저장 버튼 클릭 -> PDF 다운로드 감지
# =====================================================================

def collect_spec(driver, court_code: str, case_no: str, item_no: str, btn_id: str,
                  overwrite: bool = False) -> Dict:
    result = _empty_result()
    result["storage_type"] = "pdf"

    dest_path = os.path.join(get_doc_dir(court_code, case_no, item_no), "spec.pdf")

    if doc_exists(court_code, case_no, item_no, "spec") and not overwrite:
        logger.info("[%s-%s] spec 이미 존재. 스킵", case_no, item_no)
        result["success"] = True
        return result

    previous_hash = calc_file_hash(dest_path) if os.path.exists(dest_path) else ""

    main_handle = driver.current_window_handle
    before_handles = set(driver.window_handles)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    before_files = set(glob.glob(DOWNLOAD_DIR + os.sep + "*"))

    try:
        btn = driver.find_element(By.ID, btn_id)
        driver.execute_script("arguments[0].click();", btn)
    except Exception as e:
        logger.warning("[%s-%s] spec 버튼 클릭 실패: %s", case_no, item_no, str(e))
        return result

    # 새 탭(문서뷰어, ecfs.scourt.go.kr) 대기 - spec은 실제로 새 창이 열리는
    # 유일한 문서 종류이므로 window_handles 감지가 올바른 방식이다 (Step 2 확정 사항).
    new_handle = None
    elapsed = 0
    while elapsed < NEW_WINDOW_TIMEOUT:
        time.sleep(0.5)
        elapsed += 0.5
        new_handles = set(driver.window_handles) - before_handles
        if new_handles:
            new_handle = list(new_handles)[0]
            break

    if not new_handle:
        logger.warning("[%s-%s] spec 새 탭(문서뷰어) 감지 실패", case_no, item_no)
        return result

    try:
        driver.switch_to.window(new_handle)
        time.sleep(2)

        # "파일저장" 버튼: 정확한 id가 DOM 검증으로 확인된 적이 없으므로,
        # 화면에서 실제로 확인된 표시 텍스트("파일저장")로 탐색한다 (id 추정 금지 원칙 준수).
        save_btn = None
        for xp in [
            "//input[@value='파일저장']",
            "//a[contains(normalize-space(text()),'파일저장')]",
            "//button[contains(normalize-space(text()),'파일저장')]",
            "//*[@title='파일저장']",
        ]:
            found = driver.find_elements(By.XPATH, xp)
            if found:
                save_btn = found[0]
                break

        if not save_btn:
            logger.warning("[%s-%s] spec 문서뷰어 내 '파일저장' 버튼을 찾지 못함", case_no, item_no)
            return result

        driver.execute_script("arguments[0].click();", save_btn)

        downloaded_path = wait_for_download(before_files, timeout=30)
        if not downloaded_path:
            logger.warning("[%s-%s] spec 다운로드 미완료(타임아웃)", case_no, item_no)
            return result

        new_hash = calc_file_hash(downloaded_path)
        shutil.move(downloaded_path, dest_path)

        result["success"] = True
        result["files_saved"] = [dest_path]
        result["previous_hash"] = previous_hash
        result["new_hash"] = new_hash
        logger.info("[%s-%s] spec 저장 완료: %s", case_no, item_no, dest_path)
        return result

    finally:
        try:
            driver.close()
        except Exception:
            pass
        try:
            driver.switch_to.window(main_handle)
        except Exception:
            pass


# =====================================================================
# StatusCollector (현황조사서) - 오버레이 등장 대기 -> html/json 저장 -> 오버레이 닫기
# =====================================================================

def collect_status(driver, court_code: str, case_no: str, item_no: str, btn_id: str,
                    overwrite: bool = False) -> Dict:
    result = _empty_result()
    result["storage_type"] = "json+html"

    html_path = os.path.join(get_doc_dir(court_code, case_no, item_no), "status.html")
    json_path = os.path.join(get_doc_dir(court_code, case_no, item_no), "status.json")

    if doc_exists(court_code, case_no, item_no, "status") and not overwrite:
        logger.info("[%s-%s] status 이미 존재. 스킵", case_no, item_no)
        result["success"] = True
        return result

    previous_hash = calc_file_hash(json_path) if os.path.exists(json_path) else ""

    try:
        btn = driver.find_element(By.ID, btn_id)
        driver.execute_script("arguments[0].click();", btn)
    except Exception as e:
        logger.warning("[%s-%s] status 버튼 클릭 실패: %s", case_no, item_no, str(e))
        return result

    overlay_selector = "div[id*='curstExmndcPopUp']"
    try:
        overlay = WebDriverWait(driver, OVERLAY_TIMEOUT).until(
            lambda d: d.find_element(By.CSS_SELECTOR, overlay_selector)
        )
        # 요소 존재만이 아니라, 내부 텍스트가 채워질 때까지 대기 (Step 2에서 지적된
        # "데이터가 비동기로 채워지는 동안 빈 상태로 읽어가는" 타이밍 문제 방지)
        #
        # 2026-08-12 Sprint 62 — "비어 있지 않음"으로는 부족하다. 오버레이 골격에 고정
        # 라벨("사건번호", "조사일시" 등)이 이미 들어 있어 이 조건이 데이터 도착 전에
        # 즉시 참이 됐고, 내용 없는 페이지가 그대로 저장됐다(실측 33건).
        # 실제 사건 데이터가 채워졌는지로 판정한다.
        WebDriverWait(driver, OVERLAY_TIMEOUT).until(
            lambda d: status_overlay_has_data(
                d.find_element(By.CSS_SELECTOR, overlay_selector).text or "")
        )
    except Exception:
        logger.warning("[%s-%s] status 오버레이 등장/데이터 채움 타임아웃", case_no, item_no)
        return result

    try:
        outer_html = driver.execute_script("return arguments[0].outerHTML;", overlay)

        # 저장 직전 마지막 관문 (2026-08-12 Sprint 62).
        # 위 대기를 통과했더라도 실제로 저장할 HTML에 사건 데이터가 없으면 **저장하지
        # 않는다**. 한 번 저장되면 `doc_exists()`가 "수집 완료"로 판정해 그 물건은 영구히
        # 재수집 대상에서 빠지므로, 빈 캡처를 남기느니 실패로 두고 큐에 남기는 편이 옳다.
        if not status_overlay_has_data(outer_html):
            logger.warning("[%s-%s] status 내용이 비어 있어 저장하지 않는다(재시도 대상으로 남김)",
                           case_no, item_no)
            return result

        # 임시 파일에 먼저 쓰고 os.replace()로 원자적 교체한다(2026-08-09 Sprint 40 File/DB
        # Consistency Audit). 목적지 경로에 직접 쓰면 쓰기 도중 프로세스가 강제 종료됐을 때
        # (전원 차단, OOM kill 등 — except로 못 잡는 죽음) 잘려나간 파일이 목적지에 남을 수
        # 있다. doc_exists()는 status.json의 존재+0바이트초과만으로 "완료"를 판정하므로,
        # 손상됐지만 크기는 0이 아닌 파일이 하나라도 생기면 그 물건은 영구히 재수집 대상에서
        # 빠진다 — os.replace()는 같은 파일시스템 안에서 원자적이라 이 중간 상태 자체가
        # 존재할 수 없다(목적지는 항상 이전 내용 그대로이거나 새 내용 그대로만 남는다).
        html_tmp = html_path + ".tmp"
        with open(html_tmp, "w", encoding="utf-8") as f:
            f.write(outer_html)
        os.replace(html_tmp, html_path)

        # 구조화 데이터: 오버레이 내부에서 실제 값을 담고 있는 요소(span.w2span.txt,
        # div.w2textbox 등)를 id-텍스트 쌍으로 그대로 추출한다.
        # 필드명을 사람이 읽기 좋게 재매핑/해석하는 작업은 이번 단계에서 제외한다.
        fields = driver.execute_script("""
            var root = arguments[0];
            var out = {};
            var nodes = root.querySelectorAll("span.w2span, div.w2textbox, td, th");
            for (var i = 0; i < nodes.length; i++) {
                var el = nodes[i];
                if (!el.id) continue;
                var txt = (el.innerText || el.textContent || "").trim();
                if (txt) out[el.id] = txt;
            }
            return out;
        """, overlay)

        json_payload = {
            "extracted_at": datetime.now().isoformat(),
            "fields": fields,
        }

        json_tmp = json_path + ".tmp"
        with open(json_tmp, "w", encoding="utf-8") as f:
            json.dump(json_payload, f, ensure_ascii=False, indent=2)
        os.replace(json_tmp, json_path)

        new_hash = calc_file_hash(json_path)

        result["success"] = True
        result["files_saved"] = [html_path, json_path]
        result["previous_hash"] = previous_hash
        result["new_hash"] = new_hash
        logger.info("[%s-%s] status 저장 완료: %s / %s", case_no, item_no, html_path, json_path)
        return result

    except Exception as e:
        logger.warning("[%s-%s] status 추출 중 오류: %s", case_no, item_no, str(e))
        # html은 원본이므로, 이미 저장됐다면 "부분 성공"으로 처리하고 재시도 큐에는
        # 남기지 않는다 (json 구조화만 나중에 별도로 재시도하면 되는 문제이므로).
        if os.path.exists(html_path):
            result["success"] = True
            result["partial"] = True
            result["files_saved"] = [html_path]
            result["previous_hash"] = previous_hash
            result["new_hash"] = calc_file_hash(html_path)
        return result

    finally:
        try:
            close_btn = driver.find_element(
                By.CSS_SELECTOR, overlay_selector + " input.w2trigger.w2window_close"
            )
            driver.execute_script("arguments[0].click();", close_btn)
        except Exception:
            pass


# =====================================================================
# AppraisalCollector (감정평가서) - 오버레이 -> 중첩 iframe 진입 -> 실제 PDF URL 추출 -> 다운로드
# =====================================================================

def collect_appraisal(driver, court_code: str, case_no: str, item_no: str, btn_id: str,
                       overwrite: bool = False) -> Dict:
    result = _empty_result()
    result["storage_type"] = "pdf"

    dest_path = os.path.join(get_doc_dir(court_code, case_no, item_no), "appraisal.pdf")

    if doc_exists(court_code, case_no, item_no, "appraisal") and not overwrite:
        logger.info("[%s-%s] appraisal 이미 존재. 스킵", case_no, item_no)
        result["success"] = True
        return result

    previous_hash = calc_file_hash(dest_path) if os.path.exists(dest_path) else ""
    main_handle = driver.current_window_handle

    try:
        btn = driver.find_element(By.ID, btn_id)
        driver.execute_script("arguments[0].click();", btn)
    except Exception as e:
        logger.warning("[%s-%s] appraisal 버튼 클릭 실패: %s", case_no, item_no, str(e))
        return result

    overlay_selector = "div[id*='aeeWevlPopUp']"
    try:
        WebDriverWait(driver, OVERLAY_TIMEOUT).until(
            lambda d: d.find_element(By.CSS_SELECTOR, overlay_selector)
        )
    except Exception:
        logger.warning("[%s-%s] appraisal 오버레이 등장 타임아웃", case_no, item_no)
        return result

    pdf_url = None
    try:
        # 1단계 iframe(#sbx_iframeTest, ca.kapanet.or.kr)으로 진입
        outer_iframe = WebDriverWait(driver, OVERLAY_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, overlay_selector + " iframe#sbx_iframeTest"))
        )
        driver.switch_to.frame(outer_iframe)

        # 2단계: 그 안에서 src가 .pdf로 끝나는 iframe 탐색 (id는 매번 랜덤이므로 사용 금지)
        inner_iframes = WebDriverWait(driver, OVERLAY_TIMEOUT).until(
            lambda d: d.find_elements(By.TAG_NAME, "iframe") or False
        )
        pdf_src = None
        for f in inner_iframes:
            src = f.get_attribute("src") or ""
            if src.lower().endswith(".pdf"):
                pdf_src = src
                break

        if not pdf_src:
            logger.warning("[%s-%s] appraisal 내부 PDF iframe을 찾지 못함", case_no, item_no)
        else:
            pdf_url = urljoin(KAPANET_BASE, pdf_src)

    except Exception as e:
        logger.warning("[%s-%s] appraisal iframe 탐색 중 오류: %s", case_no, item_no, str(e))
    finally:
        driver.switch_to.default_content()

    if not pdf_url:
        try:
            close_btn = driver.find_element(
                By.CSS_SELECTOR, overlay_selector + " input.w2trigger.w2window_close"
            )
            driver.execute_script("arguments[0].click();", close_btn)
        except Exception:
            pass
        return result

    # ca.kapanet.or.kr은 courtauction.go.kr 페이지를 거쳐서 접근해야 정상 응답하는
    # 사이트이므로(직접 새 탭으로 열면 차단 안내가 뜨는 것을 확인함), 지금 열려있는
    # courtauction.go.kr 컨텍스트에서 새 탭을 연다.
    before_handles = set(driver.window_handles)
    before_files = set(glob.glob(DOWNLOAD_DIR + os.sep + "*"))
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    try:
        driver.execute_script("window.open(arguments[0]);", pdf_url)

        new_handle = None
        elapsed = 0
        while elapsed < NEW_WINDOW_TIMEOUT:
            time.sleep(0.5)
            elapsed += 0.5
            new_handles = set(driver.window_handles) - before_handles
            if new_handles:
                new_handle = list(new_handles)[0]
                break

        if not new_handle:
            logger.warning("[%s-%s] appraisal PDF 탭 생성 실패", case_no, item_no)
            return result

        driver.switch_to.window(new_handle)

        downloaded_path = wait_for_download(before_files, timeout=30)
        if not downloaded_path:
            logger.warning("[%s-%s] appraisal 다운로드 미완료(타임아웃)", case_no, item_no)
            return result

        new_hash = calc_file_hash(downloaded_path)
        shutil.move(downloaded_path, dest_path)

        result["success"] = True
        result["files_saved"] = [dest_path]
        result["previous_hash"] = previous_hash
        result["new_hash"] = new_hash
        logger.info("[%s-%s] appraisal 저장 완료: %s", case_no, item_no, dest_path)
        return result

    finally:
        try:
            if driver.current_window_handle != main_handle:
                driver.close()
        except Exception:
            pass
        try:
            driver.switch_to.window(main_handle)
        except Exception:
            pass
        try:
            close_btn = driver.find_element(
                By.CSS_SELECTOR, overlay_selector + " input.w2trigger.w2window_close"
            )
            driver.execute_script("arguments[0].click();", close_btn)
        except Exception:
            pass


# =====================================================================
# 공통 디스패처 - doc_worker는 이 함수 하나만 호출한다
# =====================================================================

def collect_document(driver, court_code: str, case_no: str, item_no: str, doc_type: str, btn_id: str,
                      overwrite: bool = False) -> Dict:
    if doc_type == "spec":
        return collect_spec(driver, court_code, case_no, item_no, btn_id, overwrite)
    if doc_type == "status":
        return collect_status(driver, court_code, case_no, item_no, btn_id, overwrite)
    if doc_type == "appraisal":
        return collect_appraisal(driver, court_code, case_no, item_no, btn_id, overwrite)

    logger.error("알 수 없는 doc_type: %s", doc_type)
    return _empty_result()
