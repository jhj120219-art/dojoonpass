import sys, os, time, re, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

DOWNLOAD_DIR = "C:\\Users\\Administrator\\Desktop\\dojun-pass\\downloads"

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
    svc = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=svc, options=opts)

def wait_loading(driver):
    try:
        WebDriverWait(driver, 30).until(
            EC.invisibility_of_element_located((By.ID, "__processbarIFrame"))
        )
    except:
        pass
    time.sleep(2)

def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    driver = build_driver()
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

        print("2. 매각물건명세서 버튼 클릭...")
        main_handle = driver.current_window_handle
        btn = driver.find_element(By.ID, "mf_wfm_mainFrame_btn_dspslGdsSpcfc1")
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(4)

        new_handles = [h for h in driver.window_handles if h != main_handle]
        if not new_handles:
            print("   새 탭 없음")
            return
        driver.switch_to.window(new_handles[0])
        time.sleep(3)
        print("   문서뷰어 탭 전환 완료")

        print("3. 파일저장 버튼 클릭...")
        before_files = set(glob.glob(DOWNLOAD_DIR + "\\*"))
        try:
            save_btn = driver.find_element(By.ID, "mf_btn_save")
            driver.execute_script("arguments[0].click();", save_btn)
            print("   클릭 완료. 8초 대기...")
            time.sleep(8)
        except Exception as e:
            print("   저장 버튼 오류:", str(e))

        after_files = set(glob.glob(DOWNLOAD_DIR + "\\*"))
        new_files = after_files - before_files
        print("   다운로드된 파일:", new_files)

        if new_files:
            pdf_path = list(new_files)[0]
            print("4. PDF 텍스트 추출:", pdf_path)
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                print("   총 페이지:", len(pdf.pages))
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    print("   [페이지", str(i+1) + "]")
                    print(text[:3000])
                    print("")
        else:
            print("4. 다운로드 실패. 폴더 확인:")
            print("   ", os.listdir(DOWNLOAD_DIR))

    except Exception as e:
        print("오류:", repr(e))
    finally:
        input("엔터를 누르면 종료...")
        driver.quit()

if __name__ == "__main__":
    main()
