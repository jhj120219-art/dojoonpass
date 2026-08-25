import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")

def build_driver():
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
        print("1. 상세페이지 진입 (서울중앙 - 임차인 있는 물건)...")
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

        print("2. 현황조사서 버튼 클릭 전 상태 저장...")
        before_handles = driver.window_handles
        before_url = driver.current_url
        print("   탭 수:", len(before_handles))
        print("   URL:", before_url)

        print("3. 현황조사서 버튼 클릭...")
        btn = driver.find_element(By.ID, "mf_wfm_mainFrame_btn_curstExmndcTop")
        driver.execute_script("arguments[0].click();", btn)
        print("   클릭 완료")

        # alert 감지
        try:
            alert = WebDriverWait(driver, 3).until(EC.alert_is_present())
            alert_text = alert.text
            print("   Alert 발생:", alert_text)
            alert.accept()
            print("   Alert 닫음")
        except Exception:   # bare 는 Ctrl-C 도 삼킨다 (Sprint 217)
            print("   Alert 없음")

        time.sleep(3)

        after_handles = driver.window_handles
        after_url = driver.current_url
        print("   클릭 후 탭 수:", len(after_handles))
        print("   클릭 후 URL:", after_url)

        if len(after_handles) > len(before_handles):
            new_handle = [h for h in after_handles if h not in before_handles][0]
            driver.switch_to.window(new_handle)
            print("   새 탭 URL:", driver.current_url)
            print("   새 탭 title:", driver.title)
            body = driver.execute_script("return document.body.innerText;") or ""
            print("   내용 앞 500자:")
            print(body[:500])
            driver.save_screenshot("debug_hyunhwang.png")
            print("   -> debug_hyunhwang.png 저장됨")
        else:
            print("   새 탭 없음")
            body = driver.execute_script("return document.body.innerText;") or ""
            print("   현재 페이지 앞 200자:")
            print(body[:200])

    except Exception as e:
        print("오류:", repr(e))
    finally:
        input("엔터를 누르면 종료...")
        driver.quit()

if __name__ == "__main__":
    main()
