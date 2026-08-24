# -*- coding: utf-8 -*-
"""`crawler.base_crawler.wait_for_detail()` 회귀 — 2026-08-24 Sprint 252 신설.

## 왜 이 파일이 생겼나

`crawler/base_crawler.py` 는 합산 커버리지 **55%** 이고, 미실행 구간은 거의 전부
Selenium 조작이라 브라우저 없이 돌릴 수 없다. **딱 한 덩어리만 예외다** —
`wait_for_detail()`(146~172행). 이 함수가 실제로 하는 판단은 셋뿐이고 전부 순수하다:

    1. 페이지 텍스트에 **기대한 사건번호**가 있는가
    2. 아직 **목록 페이지**인가 (moveDtlPage(0) 링크가 남아 있는가)
    3. 상세 지표("물건기본정보")가 있는가

드라이버를 흉내 내면 그대로 검증할 수 있다. 그런데 한 줄도 실행된 적이 없었다.

## 왜 이 판단이 중요한가 — 이 저장소가 두 번 당한 자리다

"사건번호가 맞는가"를 부분 문자열로 판정하던 결함이 **두 곳에 각각** 있었고
(`resume_start_idx()` / `go_to_case_detail()`), Sprint 121 이 하나로 합쳤다
(`crawler/resume.py:case_no_matches_list_entry`). 실측 사례:

    "2024타경1009" 가 "2024타경100920" 의 **접두 부분 문자열**이다(서로 다른 진짜 사건).

`wait_for_detail()` 은 그 공용 함수를 쓰지 않고 **자기 방식**으로 판정한다 —
`re.findall(r"\\d{4}타경\\d+")` 로 토큰을 뽑아 **집합 교집합**을 쓴다. 지금 구현은
`\\d+` 가 greedy 라 "2024타경100920" 에서 "2024타경1009" 가 떨어져 나오지 않으므로
**정확하다.** 다만 그것이 우연이 아니라 계약이라는 것을 아무것도 고정하지 않고 있었다 —
정규식이 `\\d{4}타경\\d{1,4}` 처럼 바뀌거나 `in` 비교로 되돌아가면 조용히 같은 결함이
세 번째로 살아난다. 여기서 그 계약을 못 박는다.

    python test_wait_for_detail.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


class FakeDriver(object):
    """`wait_for_detail` 이 실제로 쓰는 두 가지만 흉내 낸다.

    - `execute_script(...)`  -> 페이지 텍스트
    - `find_elements(...)`   -> 목록 링크(있으면 아직 목록 페이지)

    `pages` 를 여러 개 주면 호출할 때마다 다음 페이지로 넘어간다(로딩 중 -> 도착).
    """

    def __init__(self, pages, has_list=False):
        self.pages = list(pages)
        self.has_list = has_list
        self.script_calls = 0

    def execute_script(self, *_a, **_k):
        self.script_calls += 1
        if not self.pages:
            return ""
        if len(self.pages) == 1:
            return self.pages[0]
        return self.pages.pop(0)

    def find_elements(self, *_a, **_k):
        return ["list-link"] if self.has_list else []


DETAIL = "물건기본정보"


def run():
    import crawler.base_crawler as bc

    # 실패 경로는 40회 x 0.5초 = 20초를 기다린다. 판정 로직만 보면 되므로 잠을 없앤다.
    real_sleep = bc.time.sleep
    bc.time.sleep = lambda *_a, **_k: None
    try:
        # ── 1. 정확히 같은 사건번호 -> 도착 ────────────────────────────────
        d = FakeDriver(["%s 2024타경1009 소재지 서울" % DETAIL])
        check("정확히 일치하면 도착으로 본다", bc.wait_for_detail(d, "2024타경1009"), True)

        # ── 2. ★ 접두 부분 문자열은 도착이 아니다 (BUGS #14/#18/Sprint 121 계열) ──
        d = FakeDriver(["%s 2024타경100920 소재지 서울" % DETAIL])
        check_true("★ '2024타경1009' 가 '2024타경100920' 페이지를 자기 것으로 착각하지 않는다",
                   bc.wait_for_detail(d, "2024타경1009") is False,
                   "-> 부분 문자열 매칭으로 퇴행했다(서로 다른 진짜 사건을 같다고 본다)")

        # 반대 방향도 본다 — 긴 쪽이 짧은 쪽 페이지를 자기 것으로 보면 안 된다.
        d = FakeDriver(["%s 2024타경1009 소재지 서울" % DETAIL])
        check_true("★ 반대 방향(긴 번호가 짧은 번호 페이지)도 도착이 아니다",
                   bc.wait_for_detail(d, "2024타경100920") is False)

        # ── 3. 사건번호가 여럿이면 하나라도 나타나면 도착 ─────────────────
        d = FakeDriver(["%s 2020타경2856 소재지" % DETAIL])
        check("여러 사건번호 중 하나만 나타나도 도착",
              bc.wait_for_detail(d, "2020타경1013 / 2020타경2856"), True)

        # ── 4. 아직 목록 페이지면 도착이 아니다 ───────────────────────────
        d = FakeDriver(["%s 2024타경1009" % DETAIL], has_list=True)
        check_true("목록 링크가 남아 있으면 도착이 아니다",
                   bc.wait_for_detail(d, "2024타경1009") is False,
                   "-> 목록에서 상세로 넘어가지 않았는데 넘어갔다고 본다")

        # ── 5. 상세 지표가 없으면 도착이 아니다 ───────────────────────────
        d = FakeDriver(["2024타경1009 검색 결과"])
        check_true("'물건기본정보' 가 없으면 도착이 아니다",
                   bc.wait_for_detail(d, "2024타경1009") is False)

        # ── 6. 로딩 중이었다가 나중에 도착하는 경우 ───────────────────────
        d = FakeDriver(["로딩중...", "로딩중...", "%s 2024타경1009" % DETAIL])
        check("늦게 도착해도 잡는다(폴링)", bc.wait_for_detail(d, "2024타경1009"), True)
        check_true("검사가 공허하지 않다(폴링을 실제로 여러 번 돌았다)",
                   d.script_calls >= 3, "-> execute_script %d회" % d.script_calls)

        # ── 7. 기대 사건번호를 못 뽑는 입력 -> 상세 지표만으로 판단 ────────
        d = FakeDriver(["%s 어떤 사건" % DETAIL])
        check("사건번호를 못 뽑으면 상세 지표만으로 도착 판정", bc.wait_for_detail(d, "-"), True)
        d = FakeDriver(["%s 어떤 사건" % DETAIL], has_list=True)
        check_true("사건번호가 없어도 목록 페이지면 도착이 아니다",
                   bc.wait_for_detail(d, "") is False)

        # ── 8. 드라이버가 예외를 던져도 죽지 않고 False 로 끝난다 ──────────
        class Boom(object):
            def execute_script(self, *_a, **_k):
                raise RuntimeError("QA 주입: 드라이버 죽음")

            def find_elements(self, *_a, **_k):
                return []

        crashed = None
        try:
            got = bc.wait_for_detail(Boom(), "2024타경1009")
        except Exception as exc:      # noqa: BLE001
            crashed = "%s: %s" % (type(exc).__name__, exc)
            got = None
        check_true("드라이버 예외가 밖으로 새지 않는다", crashed is None, crashed)
        check("드라이버가 계속 죽으면 '도착 못 함'으로 끝난다", got, False)
    finally:
        bc.time.sleep = real_sleep

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
