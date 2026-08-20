import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import glob
import re
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
    existing_doc_files,
    status_overlay_has_data,
    find_sibling_case_document,
    CASE_LEVEL_DOC_TYPES,
    _PRIMARY_EXT,
)
# 병합 사건을 정확히 비교하는 판정. 같은 판정을 두 벌 만들지 않는다.
from crawler.resume import case_no_matches_list_entry

KAPANET_BASE = "https://ca.kapanet.or.kr"
OVERLAY_TIMEOUT = 15
NEW_WINDOW_TIMEOUT = 15

# 형제 물건의 사건 단위 문서를 재사용할 수 있는 최대 나이(초). 기본 6시간.
# doc_worker 가동 창(02:00~04:00, `DOC_WORKER_END_TIME`)보다 넉넉히 길고, 하루보다는
# 짧다 — "같은 실행/같은 밤에 받은 것"까지만 재사용하고 어제 것은 다시 받는다는 뜻이다.
# 같은 사건의 물건들은 auction_date와 priority가 같아 큐에서 인접해 처리되므로,
# 이 정도로도 초과 수집의 대부분이 사라진다(실측 근거는 crawler/doc_paths.py 주석).
SIBLING_REUSE_MAX_AGE_SECONDS = 6 * 3600


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
    # 이 시점에 Chrome 프로세스는 **이미 떠 있다.** 뒤이은 설정이 실패하면(브라우저가
    # 기동 직후 죽음, 연결 거부 등) 예전에는 그대로 예외가 나가면서 프로세스가 고아로
    # 남았다 — 호출자는 `driver` 참조를 받지 못했으므로 quit()을 부를 수도 없다.
    #
    # BUGS #109와 같은 계열이고 실제로 맞물린다. #109 수정으로 기동 실패 시 락은
    # 풀리지만, 실패 지점이 여기라면 좀비 크롬이 남는다. 재시도할 때마다 하나씩
    # 쌓이므로 메모리와 다운로드 폴더를 함께 갉아먹는다.
    #
    # 예외는 삼키지 않고 그대로 올린다 — 기동 실패는 호출자(doc_worker)가 인지해야 한다.
    try:
        driver.set_page_load_timeout(30)
    except Exception:
        try:
            driver.quit()
        except Exception:
            pass
        raise
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


def downloaded_file_case_no(path: str) -> Optional[str]:
    """내려받은 파일 이름에 박혀 있는 사건번호. 없으면 `None`.

    법원이 내려주는 매각물건명세서 파일명은 사건번호로 시작한다 (실측 2026-08-20,
    `downloads/` 에 남아 있던 고아 파일들):

        2023타경103287_2026.06.17_매각물건명세서(재작성,6)_참여_김윤회.pdf
        2023타경118942_2026.06.16_매각물건명세서(재작성,1)_참여_오해주.pdf

    반면 감정평가서는 **업체 코드**라 사건번호가 없다 (같은 실측):

        HR2025-0609-0001.pdf / JDG231207-2-001.pdf / sw24-041101.pdf

    그래서 이 함수는 "찾으면 돌려주고, 없으면 None" 만 한다.
    **없다고 실패로 만들지 않는다** — 사건번호를 안 넣는 문서 종류가 실제로 있다.
    """
    m = re.search(r"\d{4}타경\d+", os.path.basename(path or ""))
    return m.group(0) if m else None


def downloaded_file_belongs_to_case(path: str, case_no: str) -> bool:
    """내려받은 파일이 **지금 수집 중인 사건의 것**인가.

    ## 왜 이 검사가 필요한가 (2026-08-20 Sprint 228)

    `wait_for_download()` 는 "다운로드 폴더에 **새로 생긴** PDF" 를 집는다. 어느 사건의
    것인지는 보지 않는다. 평소에는 맞지만, **앞선 수집이 타임아웃(30초)으로 포기한 뒤에도
    그 다운로드가 계속 진행 중이면** 이야기가 달라진다.

        1. 사건 A 수집 -> 30초 안에 안 옴 -> 포기(타임아웃). 다운로드는 **계속 진행 중**
        2. 사건 B 수집 시작 -> before_files 스냅샷 (A 의 것은 아직 .crdownload)
        3. A 의 다운로드 완료 -> `A.pdf` 가 생긴다 = **새 파일**
        4. `wait_for_download()` 가 그것을 집는다 -> **A 의 문서가 B 의 것으로 저장된다**

    실제로 타임아웃은 일어난다 — `docs/SPRINT199_BATCHING_FEASIBILITY.md` 가 실행 중에
    겪었고, `downloads/` 에 고아 파일 8개(14.0MB)가 남아 있는 것이 그 흔적이다.
    그중 5개는 **같은 파일이 " (1)" " (2)" " (3)" 로 네 번** 쌓여 있다.

    그 결과는 조용하다 — PDF 이고, 크기도 정상이고, 해시도 계산되고, 화면에는 READY 로
    보인다. **사용자는 다른 사건의 매각물건명세서를 보고 입찰을 판단하게 된다.**
    이 저장소가 반복해서 잡아 온 "조용한 실패" 중에서도 결과가 가장 나쁜 쪽이다.

    ## 판정 규칙 — 확실할 때만 막는다

        파일명에 사건번호가 있다 + 다르다   -> **거부** (확실히 남의 것이다)
        파일명에 사건번호가 있다 + 같다     -> 통과
        파일명에 사건번호가 없다            -> 통과 (판단할 근거가 없다. 추측하지 않는다)

    마지막 줄이 중요하다. 감정평가서처럼 사건번호를 안 넣는 문서가 실제로 있으므로
    "없으면 거부"로 만들면 **멀쩡한 수집이 전부 막힌다.** 모르는 것은 막지 않는다.

    ## 병합 사건

    `case_no` 는 `"2008타경25092 / 2015타경19958"` 처럼 여러 사건일 수 있다(실측 22.7%).
    구성요소 각각과 **정확히** 비교한다 — 부분 문자열 비교는 하지 않는다
    (`crawler/resume.py:case_no_matches_list_entry()` 와 같은 판정을 쓴다. 같은 판정을
    두 벌 만들면 한쪽만 고쳐진다).
    """
    found = downloaded_file_case_no(path)
    if not found:
        return True                      # 판단할 근거가 없다 - 막지 않는다
    return case_no_matches_list_entry(found, case_no or "")


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


def _looks_like_pdf(path: str) -> bool:
    """실제 바이트로 PDF인지 판정한다. 확장자(`.pdf`)는 Chrome이 붙인 이름일 뿐,
    파일 내용까지 보증하지 않는다.

    법원 서버가 오류 페이지(HTML)를 `Content-Type: application/pdf`로 잘못 내려주거나,
    다운로드가 중간에 끊겨 잘린 파일이 남는 경우가 있을 수 있다. `wait_for_download()`는
    크기가 0보다 크고 두 번 연속 같은 크기인지만 본다 — "0바이트가 아니다"와 "PDF다"는
    다른 말이다. 이미지 파이프라인이 선언된 MIME을 안 믿고 매직 바이트로 판정하는 것
    (`crawler/image_assets.py:sniff_image_ext`)과 같은 이유로, 여기서도 내용을 직접 본다.

    PDF 표준(ISO 32000)은 `%PDF-`가 파일 **맨 앞**에 오는 것을 요구하지 않고 처음 1024
    바이트 안이면 허용한다(일부 도구가 앞에 바이트를 덧붙이는 경우 대비) — 그 한도를
    그대로 따른다.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(1024)
    except OSError:
        return False
    return b"%PDF-" in head


def move_into_place(src: str, dest: str) -> None:
    """다운로드 폴더의 파일을 목적지로 **원자적으로** 옮긴다.

    2026-08-18 Sprint 189 (BUGS #121). 여기는 원래 `shutil.move(src, dest)`였다.
    목적지가 없을 때는 그것으로 충분했다 — `os.rename()` 한 번이라 원자적이다.
    문제는 **목적지가 이미 있을 때**다(=재수집). Windows의 `os.rename()`은 기존 파일이
    있으면 `FileExistsError`를 내고, `shutil.move()`는 그 예외를 잡아 조용히
    `copy2()` 폴백으로 넘어간다. 실측(2026-08-18, Python 3.12.10):

        목적지 없음 -> RENAME (원자적)
        목적지 있음 -> COPY   (비원자적)   <- 재수집이 항상 여기로 온다

    비원자적 복사 도중 프로세스가 죽으면(전원 차단·OOM kill 등 except로 잡을 수 없는
    죽음) **잘린 PDF가 목적지에 남는다.** 그리고 `doc_paths.doc_exists()`는 "존재 +
    크기 0 초과"만 보므로 그 잘린 파일을 **완성된 문서로 취급**한다 — 다음 수집이
    "이미 있다"고 건너뛰어 깨진 문서가 영구히 남는다. 이 저장소가 BUGS #22/#50/#61로
    반복해 겪은 그 함정이고, 같은 동작을 하는 `collect_documents.py:249`는 이미
    `os.replace()`를 쓰고 있었다 — **두 수집기만 빠져 있었다.**

    `os.replace()`는 기존 파일이 있어도 같은 파일시스템 안에서 원자적이다. 다운로드
    폴더와 목적지가 다른 드라이브일 수 있으므로 **목적지 옆 임시 이름으로 먼저
    복사**한 뒤 교체한다(`_write_image_atomically()`와 같은 형태).
    """
    tmp = dest + ".tmp"
    try:
        os.replace(src, tmp)          # 같은 볼륨이면 이 한 번으로 끝난다
    except OSError:
        shutil.copyfile(src, tmp)     # 볼륨이 다르면 복사 후 원본 제거
        try:
            os.remove(src)
        except OSError:
            pass
    try:
        os.replace(tmp, dest)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


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
        # ★ **이미 갖고 있는 파일을 결과에 담는다** (2026-08-19 Sprint 217, BUGS #144).
        #
        #   예전에는 `files_saved` 가 빈 채로 성공을 돌려줬다. 그러면
        #   `mark_queue_done()` -> `_record_doc_raw()` 가 맨 앞에서 그냥 돌아가
        #   (`if not files_saved: return`) **파일은 있는데 doc_raw 행이 없는 상태**가
        #   큐 done / 화면 READY 로 굳는다. 그리고 다음 수집도 같은 스킵 경로를 타므로
        #   그 상태는 **영원히 스스로 회복되지 않는다**(API 의 page_count/file_size/
        #   doc_version 이 영구 null — 뷰어 페이지 이동이 그려지지 않는 상태).
        #
        #   사진 쪽은 같은 자리를 이미 복구한다(`image_crawler._describe_existing()`).
        #   문서만 없었다. `_record_doc_raw()` 는 내용이 같으면 새 행을 쌓지 않으므로
        #   (Sprint 187) 반복 실행이 버전을 부풀리지도 않는다.
        #   `previous_hash`/`new_hash` 는 그대로 비워 둔다 — 바뀐 것이 없으니
        #   `document_version_log` 에 개정을 남기면 거짓이 된다.
        result["files_saved"] = existing_doc_files(court_code, case_no,
                                                  item_no, "spec")
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

    # ★ 탭이 없다고 곧바로 실패로 끝내지 않는다 (2026-08-18 Sprint 202, BUGS #136).
    #
    #   `collect_appraisal()` 에서 고친 것과 **같은 모양**이다(BUGS #135):
    #   Chrome 은 `plugins.always_open_pdf_externally: True` 로 만들어지므로 PDF 를
    #   렌더링하지 않고 곧바로 내려받는다. 법원이 명세서를 뷰어 대신 **PDF 로 바로**
    #   내려 주는 경우, 그릴 것이 없어 탭이 뜨지 않고 파일만 도착한다.
    #
    #   증거: `downloads/` 최상위 고아 8개 중 **5개가 매각물건명세서**였다
    #   (2026-08-18 실측, 14.0MB). 즉 명세서 다운로드가 도착했는데 저장되지 않은
    #   전례가 실제로 있다.
    #
    #   그래서 탭이 없으면 **파일이 왔는지부터 본다.** 왔으면 뷰어 단계를 건너뛰고
    #   바로 저장으로 간다(뷰어는 다운로드를 얻기 위한 수단이지 목적이 아니다).
    #   둘 다 없을 때만 실패다. 더하기만 하는 변경이라 지금 성공하는 경로는 그대로다.
    direct_download = None
    if not new_handle:
        direct_download = wait_for_download(before_files, timeout=5)
        if not direct_download:
            logger.warning("[%s-%s] spec 새 탭(문서뷰어) 감지 실패 (다운로드도 오지 않았다)",
                           case_no, item_no)
            return result
        logger.info("[%s-%s] spec 탭 없이 PDF 가 바로 도착했다 - 뷰어 단계를 건너뛴다",
                    case_no, item_no)

    try:
        if direct_download is None:
            driver.switch_to.window(new_handle)
            time.sleep(2)

        if direct_download is not None:
            downloaded_path = direct_download
        else:
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
                logger.warning("[%s-%s] spec 문서뷰어 내 '파일저장' 버튼을 찾지 못함",
                               case_no, item_no)
                return result

            driver.execute_script("arguments[0].click();", save_btn)

            downloaded_path = wait_for_download(before_files, timeout=30)
            if not downloaded_path:
                logger.warning("[%s-%s] spec 다운로드 미완료(타임아웃)", case_no, item_no)
                return result

        # ★ 이 파일이 **정말 이 사건의 것인가** (2026-08-20 Sprint 228).
        #   `wait_for_download()` 는 "새로 생긴 PDF" 만 본다 — 어느 사건인지는 안 본다.
        #   앞선 수집이 타임아웃으로 포기한 뒤에도 그 다운로드가 계속 진행 중이면,
        #   그것이 **이 수집의 새 파일**로 잡혀 남의 문서가 이 사건으로 저장된다.
        #   결과가 조용하다 - PDF 이고 크기도 정상이라 화면에는 READY 로 보인다.
        #   파일명에 사건번호가 없으면(감정평가서 등) 판단하지 않고 통과시킨다.
        if not downloaded_file_belongs_to_case(downloaded_path, case_no):
            logger.error(
                "[%s-%s] %s 다운로드가 **다른 사건**의 파일이다 - 저장하지 않음: %s "
                "(앞선 수집의 지연 완료 의심)",
                case_no, item_no, "spec", os.path.basename(downloaded_path))
            # 지우지 않는다 - 원래 주인이 있는 파일이고, 지우면 그 사건의 재수집도 잃는다.
            # 고아로 남는 것은 audit_asset_integrity.py [8] 이 보고한다.
            return result

        if not _looks_like_pdf(downloaded_path):
            logger.warning("[%s-%s] spec 다운로드가 PDF가 아니다(오류 페이지/손상 의심) - 저장하지 않음: %s",
                           case_no, item_no, downloaded_path)
            try:
                os.remove(downloaded_path)
            except OSError:
                pass
            return result

        new_hash = calc_file_hash(downloaded_path)
        # ★ 바이트가 같으면 목적지를 건드리지 않는다 (2026-08-18 Sprint 189).
        #   같은 PDF를 다시 놓아도 내용은 그대로인데 mtime이 바뀌어 ETag가 달라지고,
        #   사용자는 수 MB짜리 문서를 이유 없이 다시 내려받는다(감정평가서 실측 3.4MB).
        if previous_hash and new_hash == previous_hash:
            try:
                os.remove(downloaded_path)
            except OSError:
                pass
            logger.info("[%s-%s] 내용 무변경 - 기존 파일을 그대로 둔다(브라우저 캐시 보존)",
                        case_no, item_no)
        else:
            move_into_place(downloaded_path, dest_path)

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

def _write_text_if_changed(path: str, text: str) -> bool:
    """내용이 달라졌을 때만 원자적으로 쓴다. 실제로 썼으면 True.

    2026-08-18 Sprint 189. 같은 내용을 다시 쓰면 **mtime이 바뀌고**, 서빙 쪽 ETag는
    Starlette가 (mtime, size)로 만들기 때문에 브라우저 캐시가 무의미하게 무효화된다
    (`api/http_cache.py`가 조건부 요청으로 아끼려던 바로 그 바이트다).
    재수집 대상은 정의상 "사용자가 지금 보고 있는" 물건이라 체감이 크다.
    """
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except (OSError, UnicodeDecodeError):
        pass   # 못 읽으면 "같다고 말할 수 없다" -> 쓴다
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def _fields_hash(fields) -> str:
    """현황조사서 **내용**의 지문. 우리가 찍은 메타데이터는 제외한다.

    2026-08-18 Sprint 189 (BUGS #124). 예전에는 `status.json` 파일 전체를
    `calc_file_hash()`로 떴다. 그런데 그 파일에는 우리가 매 수집마다 새로 찍는
    `extracted_at`(수집 시각)이 들어 있다. 즉 **법원 자료가 하나도 안 바뀌어도
    지문이 매번 달라진다.**

    재수집을 켜기 전에는 이 경로에 두 번 오지 않아 드러나지 않았다. 켜는 순간:

        document_version_log   매 수집마다 1행 (전부 거짓 개정)
        doc_raw.doc_version    매 수집마다 +1  (BUGS #115가 막으려던 바로 그것)
                               -> `api/v1/item.py`가 그 값을 사용자에게 그대로 싣는다

    이 저장소는 같은 함정을 이미 알고 있었다 — Sprint 145의 형제 재사용 주석이
    "차이는 우리가 찍는 extracted_at 하나뿐"이라고 실측해 적어 두었다. 그 관찰이
    변경 감지 쪽으로 연결되지 않았을 뿐이다.

    정렬된 canonical JSON을 쓰는 이유: dict 순회 순서나 들여쓰기 같은 **표현의 차이**가
    내용의 차이로 둔갑하지 않게 한다.
    """
    canon = json.dumps(fields or {}, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def status_content_hash(json_path: str) -> str:
    """디스크의 `status.json`에서 같은 공식으로 지문을 뜬다. 없거나 못 읽으면 "".

    ★ `_fields_hash()`와 **같은 공식**이어야 한다. 갈라지면 매 수집이 거짓 개정이 되어
      진짜 개정을 찾을 수 없다 — 이미지 쪽 `_existing_set_hash()`가 지고 있는 것과
      정확히 같은 책임이다(BUGS #113/#120).
    """
    try:
        with open(json_path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return _fields_hash(payload.get("fields"))


def _reuse_sibling_status(sib_dir: str, html_path: str, json_path: str,
                          court_code: str, case_no: str, item_no: str) -> Optional[Dict]:
    """형제 물건의 현황조사서를 이 물건 자리로 **복사**한다. 실패하면 None(정상 수집으로 진행).

    복사 전에 **내용을 다시 검증한다** — `status_overlay_has_data()`로 빈 캡처가 아닌지
    확인한다. 형제 파일이 어떤 이유로 비어 있다면 그것을 퍼뜨리는 것이 가장 나쁘다
    (한 번 저장되면 `doc_exists()`가 완료로 판정해 영구히 재수집에서 빠진다 — BUGS #22/#50).

    쓰기는 `os.replace()`로 원자적으로 한다 — 이 파일의 다른 저장 경로와 같은 불변식이다.
    """
    src_html = os.path.join(sib_dir, "status.html")
    src_json = os.path.join(sib_dir, "status.json")
    try:
        with open(src_html, encoding="utf-8") as f:
            html = f.read()
        with open(src_json, encoding="utf-8") as f:
            raw_json = f.read()
    except OSError as e:
        logger.warning("[%s-%s] 형제 물건 현황조사서를 읽지 못했다(%s): %s",
                       case_no, item_no, sib_dir, str(e))
        return None

    if not status_overlay_has_data(html):
        logger.warning("[%s-%s] 형제 물건의 현황조사서가 빈 캡처다. 복사하지 않고 직접 수집한다",
                       case_no, item_no)
        return None

    try:
        get_doc_dir(court_code, case_no, item_no)
        for tmp_suffix, dest, payload in ((".tmp", html_path, html), (".tmp", json_path, raw_json)):
            tmp = dest + tmp_suffix
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, dest)
    except OSError as e:
        logger.warning("[%s-%s] 현황조사서 복사 실패: %s", case_no, item_no, str(e))
        for p in (html_path + ".tmp", json_path + ".tmp"):
            try:
                os.remove(p)
            except OSError:
                pass
        return None

    result = _empty_result()
    result["storage_type"] = "json+html"
    result["success"] = True
    result["files_saved"] = [html_path, json_path]
    # 파일 전체가 아니라 **내용**의 지문이다(BUGS #124) — 복사해 온 형제 파일의
    # `extracted_at`은 그 형제를 수집한 시각이라 여기서 비교 근거가 될 수 없다.
    result["new_hash"] = status_content_hash(json_path)
    result["reused_from"] = sib_dir
    logger.info("[%s-%s] 현황조사서는 사건 단위 문서다 - 같은 사건의 %s에서 재사용(브라우저 미사용)",
                case_no, item_no, os.path.basename(sib_dir))
    return result


def collect_status(driver, court_code: str, case_no: str, item_no: str, btn_id: str,
                    overwrite: bool = False) -> Dict:
    result = _empty_result()
    result["storage_type"] = "json+html"

    html_path = os.path.join(get_doc_dir(court_code, case_no, item_no), "status.html")
    json_path = os.path.join(get_doc_dir(court_code, case_no, item_no), "status.json")

    if doc_exists(court_code, case_no, item_no, "status") and not overwrite:
        logger.info("[%s-%s] status 이미 존재. 스킵", case_no, item_no)
        result["success"] = True
        # ★ **이미 갖고 있는 파일을 결과에 담는다** (2026-08-19 Sprint 217, BUGS #144).
        #
        #   예전에는 `files_saved` 가 빈 채로 성공을 돌려줬다. 그러면
        #   `mark_queue_done()` -> `_record_doc_raw()` 가 맨 앞에서 그냥 돌아가
        #   (`if not files_saved: return`) **파일은 있는데 doc_raw 행이 없는 상태**가
        #   큐 done / 화면 READY 로 굳는다. 그리고 다음 수집도 같은 스킵 경로를 타므로
        #   그 상태는 **영원히 스스로 회복되지 않는다**(API 의 page_count/file_size/
        #   doc_version 이 영구 null — 뷰어 페이지 이동이 그려지지 않는 상태).
        #
        #   사진 쪽은 같은 자리를 이미 복구한다(`image_crawler._describe_existing()`).
        #   문서만 없었다. `_record_doc_raw()` 는 내용이 같으면 새 행을 쌓지 않으므로
        #   (Sprint 187) 반복 실행이 버전을 부풀리지도 않는다.
        #   `previous_hash`/`new_hash` 는 그대로 비워 둔다 — 바뀐 것이 없으니
        #   `document_version_log` 에 개정을 남기면 거짓이 된다.
        result["files_saved"] = existing_doc_files(court_code, case_no,
                                                  item_no, "status")
        return result

    # 사건 단위 문서 재사용 (2026-08-17 Sprint 145).
    #
    # 현황조사서는 **사건 하나에 문서 하나**다(집행관이 사건 단위로 작성한다).
    # 그래서 같은 사건의 다른 물건이 방금 받아 둔 것이 있으면 브라우저를 다시 몰 이유가
    # 없다 — 실측으로 status.html은 바이트까지 같고, status.json도 `fields` 115개 키가
    # 완전히 일치했다(차이는 우리가 찍는 extracted_at 하나뿐).
    #
    # 비용 근거: 사건 1,384개 / 물건 1,876개라 초과 수집이 492회이고, worker 1건이
    # 약 22초이니 **약 3시간**이다(가동 창 02:00~04:00 = 2시간을 넘긴다).
    # (★ 2026-08-17 Sprint 147 정정: 이 '약 3시간'은 navigation까지 건너뛴다고 **가정한** 값이다. Sprint 145 구현은 `collect_status()` 안에서만 재사용해 물건당 0.6초(overlay)만 아꼈고 navigation 15.2초는 그대로 들었다 — 실제 절감 492회 기준 **5분**. Sprint 147이 doc_worker의 호출 순서를 바꿔(재사용 가능하면 이동 자체를 생략) 실 worker 2건 기준 41.1초 -> 23.8초, 492회 기준 **약 130분** 절감으로 실현했다.)
    #
    # ★ `SIBLING_REUSE_MAX_AGE_SECONDS`로 **같은 실행에서 방금 받은 것만** 재사용한다.
    #   몇 달 전 파일을 복사하면 새로 받았다면 얻었을 최신본 대신 옛것을 주게 되는데,
    #   "언제 다시 받을 것인가"는 재수집 정책(미결정, docs/roadmap.md)이라 여기서
    #   정하지 않는다. 보수적으로 좁혀 두면 정책이 정해질 때 이 값만 조정하면 된다.
    if not overwrite:
        sib = find_sibling_case_document(court_code, case_no, item_no, "status",
                                          max_age_seconds=SIBLING_REUSE_MAX_AGE_SECONDS)
        if sib:
            reused = _reuse_sibling_status(sib, html_path, json_path, court_code,
                                           case_no, item_no)
            if reused:
                return reused

    # ★ 파일 전체 해시가 아니라 **내용** 해시다 (2026-08-18 Sprint 189, BUGS #124).
    #   status.json 에는 우리가 매번 새로 찍는 `extracted_at`이 들어 있어, 파일을 통째로
    #   해싱하면 법원 자료가 그대로여도 지문이 매번 달라진다(= 매 수집이 거짓 개정).
    previous_hash = status_content_hash(json_path)

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
        # 내용이 그대로면 쓰지 않는다(위 `_write_text_if_changed()` 참고). 원자성 규약은
        # 그 헬퍼 안에 그대로 있다 — 임시 파일 + os.replace().
        _write_text_if_changed(html_path, outer_html)

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

        new_hash = _fields_hash(fields)

        # ★ 내용이 그대로면 **다시 쓰지 않는다** (2026-08-18 Sprint 189).
        #
        #   법원 자료가 안 바뀌었는데 파일을 다시 쓰면 mtime이 바뀌고, 서빙 쪽 ETag는
        #   (mtime, size)로 만들어지므로 **모든 브라우저 캐시가 무의미하게 무효화된다**
        #   (`api/http_cache.py`가 아끼려던 바로 그 바이트다). 재수집 대상은 정의상
        #   "사용자가 지금 보고 있는" 물건이라 체감이 크다.
        #
        #   `extracted_at`은 옛 값 그대로 남는다 — 이제 그 필드의 뜻은 "이 내용을 처음
        #   확인한 수집 시각"이다. 매 수집 시각을 남기는 것보다 이쪽이 더 쓸모 있다.
        if new_hash and new_hash == previous_hash and os.path.exists(html_path):
            result["success"] = True
            result["files_saved"] = [html_path, json_path]
            result["previous_hash"] = previous_hash
            result["new_hash"] = new_hash
            logger.info("[%s-%s] status 내용 무변경 - 파일을 다시 쓰지 않는다"
                        "(브라우저 캐시 보존)", case_no, item_no)
            return result

        json_payload = {
            "extracted_at": datetime.now().isoformat(),
            "fields": fields,
        }

        _write_text_if_changed(
            json_path, json.dumps(json_payload, ensure_ascii=False, indent=2))

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
        # ★ **이미 갖고 있는 파일을 결과에 담는다** (2026-08-19 Sprint 217, BUGS #144).
        #
        #   예전에는 `files_saved` 가 빈 채로 성공을 돌려줬다. 그러면
        #   `mark_queue_done()` -> `_record_doc_raw()` 가 맨 앞에서 그냥 돌아가
        #   (`if not files_saved: return`) **파일은 있는데 doc_raw 행이 없는 상태**가
        #   큐 done / 화면 READY 로 굳는다. 그리고 다음 수집도 같은 스킵 경로를 타므로
        #   그 상태는 **영원히 스스로 회복되지 않는다**(API 의 page_count/file_size/
        #   doc_version 이 영구 null — 뷰어 페이지 이동이 그려지지 않는 상태).
        #
        #   사진 쪽은 같은 자리를 이미 복구한다(`image_crawler._describe_existing()`).
        #   문서만 없었다. `_record_doc_raw()` 는 내용이 같으면 새 행을 쌓지 않으므로
        #   (Sprint 187) 반복 실행이 버전을 부풀리지도 않는다.
        #   `previous_hash`/`new_hash` 는 그대로 비워 둔다 — 바뀐 것이 없으니
        #   `document_version_log` 에 개정을 남기면 거짓이 된다.
        result["files_saved"] = existing_doc_files(court_code, case_no,
                                                  item_no, "appraisal")
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

        # ★ 탭이 안 생겼다고 실패로 끝내지 않는다 (2026-08-18 Sprint 201, BUGS #135).
        #
        #   `get_download_driver_options()` 는 `plugins.always_open_pdf_externally: True`
        #   를 켠다. 그래서 Chrome 은 PDF 를 **렌더링하지 않고 곧바로 내려받는다** —
        #   `window.open()` 으로 연 탭은 그리는 것이 없으니 뜨지도 않고 사라진다.
        #   즉 **다운로드가 성공할수록 탭은 안 생긴다.** 탭을 성공 조건으로 삼은 것이
        #   구조적으로 틀렸다.
        #
        #   실측(2026-08-18): 이 경로가 "탭 생성 실패"로 끝난 실행에서 `downloads/` 에
        #   2,528,908 바이트 PDF 가 도착해 있었고, 그 물건의 기존 `appraisal.pdf` 와
        #   **sha256 이 일치**했다. 즉 받아 놓고 버린 것이다. `downloads/` 최상위에
        #   고아 PDF 8개가 쌓여 있었고 그중 4개는 같은 문서의 Chrome 중복 이름
        #   (`... (1).pdf` ~ `(3).pdf`)이었다 — **같은 문서를 네 번 받아 네 번 버렸다.**
        #
        #   그래서 탭이 없으면 **다운로드가 왔는지부터 확인한다.** 둘 다 없을 때만 실패다.
        #   (이 변경은 더할 뿐이다 — 지금 성공하는 경로는 그대로 두고, 지금 실패하는
        #    경로만 성공으로 바뀔 수 있다.)
        if new_handle:
            driver.switch_to.window(new_handle)
        else:
            logger.info("[%s-%s] appraisal PDF 탭이 뜨지 않았다 "
                        "(PDF 외부열기 설정이면 정상) - 다운로드 도착 여부로 판단한다",
                        case_no, item_no)

        downloaded_path = wait_for_download(before_files, timeout=30)
        if not downloaded_path:
            if new_handle:
                logger.warning("[%s-%s] appraisal 다운로드 미완료(타임아웃)", case_no, item_no)
            else:
                logger.warning("[%s-%s] appraisal: 탭도 안 뜨고 다운로드도 오지 않았다",
                               case_no, item_no)
            return result

        # ★ 이 파일이 **정말 이 사건의 것인가** (2026-08-20 Sprint 228).
        #   `wait_for_download()` 는 "새로 생긴 PDF" 만 본다 — 어느 사건인지는 안 본다.
        #   앞선 수집이 타임아웃으로 포기한 뒤에도 그 다운로드가 계속 진행 중이면,
        #   그것이 **이 수집의 새 파일**로 잡혀 남의 문서가 이 사건으로 저장된다.
        #   결과가 조용하다 - PDF 이고 크기도 정상이라 화면에는 READY 로 보인다.
        #   파일명에 사건번호가 없으면(감정평가서 등) 판단하지 않고 통과시킨다.
        if not downloaded_file_belongs_to_case(downloaded_path, case_no):
            logger.error(
                "[%s-%s] %s 다운로드가 **다른 사건**의 파일이다 - 저장하지 않음: %s "
                "(앞선 수집의 지연 완료 의심)",
                case_no, item_no, "appraisal", os.path.basename(downloaded_path))
            # 지우지 않는다 - 원래 주인이 있는 파일이고, 지우면 그 사건의 재수집도 잃는다.
            # 고아로 남는 것은 audit_asset_integrity.py [8] 이 보고한다.
            return result

        if not _looks_like_pdf(downloaded_path):
            logger.warning("[%s-%s] appraisal 다운로드가 PDF가 아니다(오류 페이지/손상 의심) - 저장하지 않음: %s",
                           case_no, item_no, downloaded_path)
            try:
                os.remove(downloaded_path)
            except OSError:
                pass
            return result

        new_hash = calc_file_hash(downloaded_path)
        # ★ 바이트가 같으면 목적지를 건드리지 않는다 (2026-08-18 Sprint 189).
        #   같은 PDF를 다시 놓아도 내용은 그대로인데 mtime이 바뀌어 ETag가 달라지고,
        #   사용자는 수 MB짜리 문서를 이유 없이 다시 내려받는다(감정평가서 실측 3.4MB).
        if previous_hash and new_hash == previous_hash:
            try:
                os.remove(downloaded_path)
            except OSError:
                pass
            logger.info("[%s-%s] 내용 무변경 - 기존 파일을 그대로 둔다(브라우저 캐시 보존)",
                        case_no, item_no)
        else:
            move_into_place(downloaded_path, dest_path)

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
    if doc_type == "image":
        # 2026-08-17 Sprint 144: 물건 사진. `btn_id`를 쓰지 않는다 — 사진은 버튼을 눌러
        # 여는 것이 아니라 상세페이지 DOM에 이미 들어 있다(crawler/image_crawler.py 참고).
        # import를 함수 안에서 하는 이유: 이 모듈은 하위 호환 재노출 창구라
        # 최상단 import를 늘리면 `from crawler.doc_crawler import get_doc_dir`처럼
        # 경로 규칙만 쓰는 쪽까지 새 모듈을 끌어가게 된다.
        from crawler.image_crawler import collect_images
        return collect_images(driver, court_code, case_no, item_no, overwrite)

    logger.error("알 수 없는 doc_type: %s", doc_type)
    return _empty_result()
