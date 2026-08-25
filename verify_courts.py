import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
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

def main():
    driver = build_driver()
    try:
        print("1. 기일별검색 페이지 접속...")
        driver.get(
            "https://www.courtauction.go.kr/pgj/index.on"
            "?w2xPath=/pgj/ui/pgj100/PGJ153F00.xml"
        )
        time.sleep(5)

        print("2. 법원 드롭다운 옵션 전체 출력...")
        selects = driver.find_elements(By.TAG_NAME, "select")
        print("   select 태그 수:", len(selects))

        for s_idx, sel in enumerate(selects):
            sel_id = sel.get_attribute("id") or ""
            sel_name = sel.get_attribute("name") or ""
            options = sel.find_elements(By.TAG_NAME, "option")
            print("")
            print("  [select " + str(s_idx) + "] id=" + sel_id + " name=" + sel_name)
            print("  옵션 수:", len(options))
            for opt in options:
                val = opt.get_attribute("value") or ""
                txt = opt.text.strip()
                print("    value=" + val + " | text=" + txt)

        print("")
        print("3. JavaScript로 법원 select 탐색...")
        result = driver.execute_script("""
            var selects = document.querySelectorAll('select');
            var data = [];
            selects.forEach(function(sel) {
                var opts = [];
                sel.querySelectorAll('option').forEach(function(opt) {
                    opts.push({value: opt.value, text: opt.text.trim()});
                });
                data.push({id: sel.id, name: sel.name, options: opts});
            });
            return data;
        """)
        print("   JS로 찾은 select 수:", len(result) if result else 0)
        if result:
            for sel_info in result:
                print("   id=" + str(sel_info.get("id")) + " name=" + str(sel_info.get("name")))
                for opt in sel_info.get("options", []):
                    print("     value=" + str(opt.get("value")) + " | text=" + str(opt.get("text")))

    except Exception as e:
        print("오류:", repr(e))
    finally:
        input("엔터를 누르면 종료...")
        driver.quit()

if __name__ == "__main__":
    main()
