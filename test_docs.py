import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --- 실행 가드 (2026-08-11 Sprint 55, docs/BUGS.md #51) -----------------------
# 이 파일은 이름이 test_*.py이지만 **테스트가 아니다.** assert가 하나도 없고 PASS/FAIL도
# 없으며, 실제 `courtauction.go.kr`에 접속해 크롤링한다(일부는 `input()`으로 사람 입력까지
# 기다린다).
#
# 문서에는 "회귀에서 자동 실행하지 않는다"고 여러 곳에 적혀 있었지만, 그것은 **규약**일 뿐
# 아무것도 막지 못했다. 실제로 2026-08-11 감사 중 `test_*.py`를 전부 실행하는 스윕이
# 두 번 돌았고, selenium이 설치돼 있지 않아서 **우연히** 실제 접속이 일어나지 않았을 뿐이다.
# 규약 대신 구조로 막는다.
#
# 파일명을 바꾸지 않는 이유: 이 이름이 docs 6개 파일에 참조돼 있어, 이름을 바꾸면
# 문서가 한꺼번에 낡는다. 이름은 두고 **실행만** 막는 편이 부작용이 작다.
if __name__ == "__main__" and os.environ.get("ALLOW_LIVE_CRAWL") != "1":
    print("[SKIPPED] %s 는 실제 법원 사이트에 접속하는 수동 스크립트입니다 (회귀 대상 아님)."
          % os.path.basename(__file__))
    print("          실행하려면 명시적으로 허용하십시오:  ALLOW_LIVE_CRAWL=1 python %s"
          % os.path.basename(__file__))
    raise SystemExit(0)
# -----------------------------------------------------------------------------

import time
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from crawler.doc_crawler import get_download_driver_options, wait_loading, crawl_documents

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    opts = get_download_driver_options()
    # ★ 드라이버 해석은 crawler.base_crawler 한 곳에 있다 (2026-08-25, docs/BUGS.md #196).
    #   직접 ChromeDriverManager 를 부르면 이 PC 에서 기동에 실패한다.
    from crawler.base_crawler import resolve_chrome_driver
    driver = resolve_chrome_driver(opts)

    try:
        print("1. 상세페이지 진입...")
        driver.get("https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ153F00.xml")
        time.sleep(5)
        driver.find_element(By.ID, "mf_wfm_mainFrame_btn_rletSrch").click()
        wait_loading(driver)
        first_link = driver.find_element(By.XPATH,
            "//a[@onclick and contains(@onclick,'moveDtlUrl')]")
        driver.execute_script("arguments[0].click();", first_link)
        wait_loading(driver)
        driver.execute_script("moveDtlPage(0)")
        time.sleep(5)
        print("   완료")

        print("2. 문서 크롤링 시작...")
        result = crawl_documents(driver, "2023타경118942")

        print("")
        print("===== 매각물건명세서 파싱 결과 =====")
        parsed = result["myungseso_parsed"]
        tenants = parsed.get("tenants", [])
        print("임차인 수:", len(tenants))
        for t in tenants:
            print("  이름:", t.get("name"))
            print("  점유부분:", t.get("area"))
            print("  보증금:", t.get("deposit"))
            print("  전입일:", t.get("move_in_date"))
            print("  확정일:", t.get("fixed_date"))
            print("  배당요구일:", t.get("demand_date"))
            print()
        print("권리관계:", parsed.get("rights", []))

        print("")
        print("===== 현황조사서 파싱 결과 =====")
        hyun = result["hyunhwang_parsed"]
        print("점유상태:", hyun.get("occupancy_status"))
        print("공실여부:", hyun.get("is_vacant"))
        print("점유자유형:", hyun.get("occupant_type"))
        print("사업장운영:", hyun.get("business_active"))

    except Exception as e:
        print("오류:", repr(e))
    finally:
        input("엔터를 누르면 종료...")
        driver.quit()

if __name__ == "__main__":
    main()
