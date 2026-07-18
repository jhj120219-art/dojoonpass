import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from crawler.doc_crawler import get_download_driver_options, wait_loading, crawl_documents

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    opts = get_download_driver_options()
    svc = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=svc, options=opts)

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
