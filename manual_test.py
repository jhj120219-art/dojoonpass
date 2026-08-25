import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def build_driver():
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    # ★ 드라이버 해석은 crawler.base_crawler 한 곳에 있다 (2026-08-25, docs/BUGS.md #196).
    #   직접 ChromeDriverManager 를 부르면 이 PC 에서 기동에 실패한다.
    from crawler.base_crawler import resolve_chrome_driver
    return resolve_chrome_driver(opts)

def wait_loading(driver):
    try:
        WebDriverWait(driver, 30).until(
            EC.invisibility_of_element_located((By.ID, "__processbarIFrame"))
        )
    except Exception:   # bare 는 Ctrl-C 도 삼킨다 (Sprint 217)
        pass
    time.sleep(2)

def main():
    driver = build_driver()
    try:
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
        print("상세페이지 진입 완료")
        print("브라우저에서 현황조사서 버튼을 직접 클릭해보세요")
        print("새 탭이 열리는지, 팝업인지, 로그인 화면인지 확인하세요")
        input("확인 후 엔터...")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
