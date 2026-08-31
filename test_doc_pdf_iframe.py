# -*- coding: utf-8 -*-
"""`crawler.doc_crawler._pdf_iframe_src()` 회귀 — 2026-08-31 신설.

## 왜 이 파일이 생겼나 — **주석이 가리키던 검사가 없었다**

`crawler/doc_crawler.py` 의 `_pdf_iframe_src()` docstring 이 이렇게 적고 있었다.

    함수로 뺀 두 번째 이유는 **브라우저 없이 검증할 수 있게** 하려는 것이다.
    ... 순수한 판단만 떼어 내면 가짜 드라이버로 회귀를 걸 수 있다
    (`test_doc_pdf_iframe.py`).

2026-08-31 실측: **그 파일은 존재하지 않았고 이 함수는 한 줄도 실행된 적이 없었다.**
저장소 전체에서 `_pdf_iframe_src` 를 부르는 곳은 `doc_crawler.py` 자신뿐이다.
검증 가능하게 만들어 두고 검증하지 않은 상태였다 — 이 저장소가 반복해 잡아 온
"공허한 보증"과 같은 계열이다(같은 날 `normalizer/mylist_import.py` 에서도 없는
검사 파일을 가리키는 주석을 하나 찾아 정정했다).

## 무엇이 걸린 문제인가 (docs/BUGS.md #267)

문서 뷰어는 iframe 을 **먼저 붙이고 src 를 나중에 채운다.** 예전 구현은 "iframe 이
하나라도 생겼는가"를 기다린 뒤 src 를 한 번만 훑어서, 그 한 번이 대개 너무 일렀다.
지금은 이 함수를 `WebDriverWait(...).until()` 의 **조건 자체**로 쓴다 —
`until()` 은 None 을 받으면 계속 폴링하므로 "필요한 것이 생길 때까지" 기다린다.

그래서 이 함수의 계약은 두 겹이다.

    1. 아직 준비되지 않았으면 **반드시 None**  (False/"" 등을 돌려주면 폴링이 멈춘다)
    2. 폴링 중의 DOM 교체(stale element)나 드라이버 예외에 **죽지 않는다**

둘 중 하나만 깨져도 증상은 "문서를 못 받는다"인데 원인은 로그에 남지 않는다.

    python test_doc_pdf_iframe.py
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


class FakeFrame(object):
    """`get_attribute("src")` 만 흉내 낸다. `src=None` 이면 아직 안 채워진 iframe."""

    def __init__(self, src, raises=False):
        self.src = src
        self.raises = raises

    def get_attribute(self, _name):
        if self.raises:
            # 폴링 도중 DOM 이 교체되면 selenium 이 실제로 이 계열의 예외를 던진다.
            raise RuntimeError("QA 주입: stale element")
        return self.src


class FakeDriver(object):
    """`find_elements(By.TAG_NAME, "iframe")` 만 흉내 낸다.

    `frame_sets` 를 여러 개 주면 호출할 때마다 다음 상태로 넘어간다
    (iframe 이 붙었지만 src 가 비어 있는 순간 -> src 가 채워진 순간).
    """

    def __init__(self, frame_sets, raises=False):
        self.frame_sets = list(frame_sets)
        self.raises = raises
        self.calls = 0

    def find_elements(self, *_a, **_k):
        self.calls += 1
        if self.raises:
            raise RuntimeError("QA 주입: 드라이버 죽음")
        if not self.frame_sets:
            return []
        if len(self.frame_sets) == 1:
            return self.frame_sets[0]
        return self.frame_sets.pop(0)


def run():
    from crawler.doc_crawler import _pdf_iframe_src as pdf_src

    # ── 0. 검사가 공허하지 않다 ────────────────────────────────────────────
    d = FakeDriver([[FakeFrame("https://ca.kapanet.or.kr/a/b.pdf")]])
    check("검사 대상 함수가 실제로 값을 돌려준다",
          pdf_src(d), "https://ca.kapanet.or.kr/a/b.pdf")
    check_true("드라이버를 실제로 훑었다", d.calls == 1, d.calls)

    # ── 1. .pdf 로 끝나는 src 만 고른다 ────────────────────────────────────
    d = FakeDriver([[
        FakeFrame("https://x/viewer.html"),
        FakeFrame("https://x/doc.pdf"),
        FakeFrame("https://x/other.pdf"),
    ]])
    check("여러 iframe 중 첫 번째 .pdf 를 고른다", pdf_src(d), "https://x/doc.pdf")

    d = FakeDriver([[FakeFrame("https://x/DOC.PDF")]])
    check("확장자 대문자도 받는다(판정은 소문자 비교다)", pdf_src(d), "https://x/DOC.PDF")

    # ── 2. ★ 아직 준비되지 않았으면 **None** 이어야 한다 ───────────────────
    #    `WebDriverWait.until()` 은 None/False 를 "아직"으로 보고 계속 폴링한다.
    #    여기서 "" 를 돌려주면 falsy 라 폴링은 계속되지만, 이후 값이 채워졌을 때
    #    호출부가 문자열을 기대하는 자리에서 형이 갈린다. None 으로 못박는다.
    check("iframe 자체가 없으면 None", pdf_src(FakeDriver([[]])), None)
    check("iframe 은 있는데 src 가 아직 없으면 None",
          pdf_src(FakeDriver([[FakeFrame(None)]])), None)
    check("src 가 빈 문자열이어도 None",
          pdf_src(FakeDriver([[FakeFrame("")]])), None)
    check("pdf 가 아닌 iframe 만 있으면 None",
          pdf_src(FakeDriver([[FakeFrame("https://x/viewer.html")]])), None)

    # ── 3. ★ 폴링 시나리오 — 늦게 채워지는 src 를 결국 잡는다 ─────────────
    #    이것이 BUGS #267 이 고친 그 상황이다(붙는 시점과 채워지는 시점이 다르다).
    d = FakeDriver([
        [FakeFrame(None)],                     # 1회차: 아직 비어 있다
        [FakeFrame("https://x/late.pdf")],     # 2회차: 채워졌다
    ])
    check("1회차에는 아직 None", pdf_src(d), None)
    check("2회차에 값을 잡는다", pdf_src(d), "https://x/late.pdf")

    # ── 4. 쿼리스트링이 붙은 src 는 **지금은 잡지 않는다**(알려진 한계) ────
    #    docstring 이 "실 사이트 확인이 필요해 건드리지 않았다"고 적어 둔 자리다.
    #    고쳐야 한다는 뜻이 아니라, **지금 동작이 무엇인지** 못박아 둔다 —
    #    나중에 규칙을 넓힐 때 이 줄이 그 변경을 의식적으로 만들게 한다.
    check("쿼리스트링이 붙으면 잡지 못한다(현재 계약)",
          pdf_src(FakeDriver([[FakeFrame("https://x/doc.pdf?token=1")]])), None)

    # ── 5. ★ 예외에 죽지 않는다 ───────────────────────────────────────────
    #    폴링 중 DOM 교체는 정상이다. 여기서 예외가 새면 `until()` 이 통째로 끝나
    #    "문서를 못 받았다"가 되는데, 원인은 stale element 하나뿐이다.
    d = FakeDriver([[FakeFrame(None, raises=True), FakeFrame("https://x/ok.pdf")]])
    crashed = None
    try:
        got = pdf_src(d)
    except Exception as exc:                    # noqa: BLE001
        crashed = "%s: %s" % (type(exc).__name__, exc)
        got = "<예외>"
    check_true("stale element 예외가 밖으로 새지 않는다", crashed is None, crashed)
    check("죽은 frame 을 건너뛰고 다음 frame 을 본다", got, "https://x/ok.pdf")

    d = FakeDriver([], raises=True)
    crashed = None
    try:
        got = pdf_src(d)
    except Exception as exc:                    # noqa: BLE001
        crashed = "%s: %s" % (type(exc).__name__, exc)
        got = "<예외>"
    check_true("드라이버 예외가 밖으로 새지 않는다", crashed is None, crashed)
    check("드라이버가 죽으면 '아직 없음'(None)으로 끝난다", got, None)

    # ── 6. 주석이 가리키는 검사 파일이 실제로 존재한다 ────────────────────
    #    이 파일이 생긴 이유 그 자체. 없는 파일을 가리키는 주석은 거짓 보증이다.
    import re
    root = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(root, "crawler", "doc_crawler.py"),
               encoding="utf-8-sig").read()
    cited = sorted(set(re.findall(r"\btest_[A-Za-z0-9_]+\.py", src)))
    check_true("주석이 검사 파일을 실제로 가리킨다(검사가 공허하지 않다)", bool(cited), cited)
    missing = [c for c in cited if not os.path.exists(os.path.join(root, c))]
    check("존재하지 않는 검사 파일을 가리키지 않는다", missing, [])

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
