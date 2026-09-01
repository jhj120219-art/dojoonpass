"""좁은 폭 레이아웃/접근성을 **진짜 브라우저 뷰포트**로 잰다 (2026-08-21 Sprint 242 신설).

    python audit_viewport.py                    # 기본 6폭 x 전 화면
    python audit_viewport.py --width 320        # 한 폭만
    python audit_viewport.py --base http://localhost:3000
    python audit_viewport.py --headed           # 창을 띄워서 눈으로 확인

종료 코드: 결함이 하나라도 있으면 1, 없으면 0.
서버가 없거나 브라우저를 못 띄우면 **2**(측정 불가) — 0(정상)으로 뭉개지 않는다.

---------------------------------------------------------------------------
왜 이 파일이 필요했나 — 가짜 뷰포트로 "정상"을 판정할 뻔했다
---------------------------------------------------------------------------

이 저장소는 Sprint 219 이래 좁은 폭을 못 쟀다. 시도한 것과 실패한 이유:

    resize_window(390x844)   호출은 성공하는데 innerWidth 가 안 바뀐다   (Sprint 223)
    iframe 에 앱을 띄우기      X-Frame-Options: DENY 에 막힌다            (Sprint 224)
    서브트리를 고정폭 상자에 복제  레이아웃은 진짜지만 **미디어쿼리는 여전히
                              바깥 뷰포트(1568px)로 평가된다**            (Sprint 231)
    iframe + srcdoc           뷰포트는 진짜인데 Suspense 스트리밍 화면(상세)이
                              완성되지 않는다                            (Sprint 240)

Sprint 240/241 은 결국 `window.open(url,'','width=320')` 으로 **진짜 창**을 띄워
쟀고 그제서야 실제 결함 3종(헤더 넘침 / 검색조건 저장 줄 / 목록 카드 grid 트랙)이
드러났다. 그런데 그 방법은 **사람이 브라우저 세션 안에서 손으로** 하는 것이라
다시 재려면 매번 처음부터 해야 했다.

이 파일은 그 측정을 **재실행 가능한 도구로 고정한다.** 새 의존성은 없다 —
`selenium` + `webdriver_manager` 는 크롤러가 이미 쓰고 있다(requirements.txt).

---------------------------------------------------------------------------
★ 이 도구가 스스로를 의심하는 방법
---------------------------------------------------------------------------

이 저장소에서 **측정 도구 자체가 여러 번 오탐을 냈다**(oklch 대비 계산, 헤더
대소문자, fixture .env, 가짜 뷰포트). 그래서 매 측정마다 세 가지를 함께 확인한다.

    1. 뷰포트가 진짜인가   요청 폭과 `window.innerWidth` 가 실제로 맞는가.
                          어긋나면 그 측정을 **버린다**(정상이라고 하지 않는다).
    2. 탐지기가 살아 있는가 일부러 넓은 요소를 넣어 잡히는지 확인하고 뺀다.
                          안 잡히면 그 측정을 버린다.
    3. CSS 가 붙었는가     Tailwind 유틸리티가 실제로 적용되는지 확인한다.
                          스타일이 안 붙은 화면은 "넘침 0"이 당연하므로 무의미하다.

---------------------------------------------------------------------------
★ 넘침의 정의 — 스크롤 컨테이너 안은 넘침이 아니다
---------------------------------------------------------------------------

정렬 칩 줄처럼 `overflow-x:auto` 안에서 옆으로 흐르는 것은 **의도된 디자인**이다.
그것을 결함으로 세면 도구가 매번 거짓 경보를 낸다. 그래서 두 가지를 나눈다.

    페이지 가로 스크롤   documentElement.scrollWidth > clientWidth   <- 결함
    REAL 넘침           뷰포트 밖인데 **스크롤 조상이 없다**          <- 결함
    컨테이너 내 넘침     스크롤 조상이 있다                          <- 정상(세지 않는다)

---------------------------------------------------------------------------
★ 로그인이 필요한 화면은 "통과"가 아니라 "측정 못 함"이다
---------------------------------------------------------------------------

헤드리스 브라우저에는 사용자 세션이 없다. `/favorites` 등은 `/login` 으로
튕기는데, 그 로그인 화면은 단순해서 **당연히 넘치지 않는다.** 그것을 통과로
세면 이 저장소가 반복해 겪은 "실패 != 없음"을 그대로 재현하는 것이다.
그래서 요청한 경로와 실제 도착한 경로가 다르면 `AUTH` 로 따로 표시하고
합격/불합격 어느 쪽으로도 세지 않는다.
"""
import argparse
import json
import os
import sys

BASE_DEFAULT = "http://localhost:3000"
WIDTHS_DEFAULT = [320, 360, 390, 430, 900, 1400]

# 검색 화면의 기본 조건. **결과 카드가 실제로 그려져야** 의미가 있는 화면이다.
SEARCH_PATH = "/search?sido=%EC%84%9C%EC%9A%B8"

# 카드가 0장일 때 한 번 더 시도할 조건.
#
# ★ 왜 필요한가 — 이 도구가 "결함 0"이라고 말하면서 **가장 복잡한 화면을 아예 안 재고**
#   있었다(2026-09-01 실측). 기일이 지난 물건만 남은 DB(개발/QA 머신이 그렇다)에서는
#   기본 검색이 0건이라, 재는 것은 **카드가 하나도 없는 빈 목록**이다. 빈 목록은
#   당연히 넘치지 않는다. Sprint 240 이 좁은 폭에서 찾아낸 결함 3종 중 **둘이 바로
#   그 카드**(목록 카드 grid 트랙 / 물건종류 배지)에 있었는데, 그 화면을 안 재고
#   초록을 찍고 있었던 셈이다. 상세 화면도 표본 id 를 검색 결과에서 뽑으므로
#   **통째로 건너뛰어졌다** — 그런데도 종료코드는 0이었다.
#
#   `include_closed=true` 는 UI 에도 있는 정식 검색 조건이다(SearchForm 의
#   "종결 포함"). 데이터를 만들어 넣지 않고, 있는 데이터를 보이게만 한다.
SEARCH_PATH_WITH_CLOSED = SEARCH_PATH + "&include_closed=true"

# (경로, 최소 노드 수) — 최소 노드 수는 "화면이 실제로 그려졌는가"의 하한이다.
SCREENS = [
    ("/", 200),
    (SEARCH_PATH, 200),
    ("/favorites", 30),
    ("/properties/recent", 30),
    ("/mypage", 20),
    ("/login", 20),
]

# 상세는 물건 id 가 필요하다 — 검색 결과에서 실행 시점에 하나 골라 붙인다.
DETAIL_FROM_SEARCH = True


MEASURE_JS = r"""
const want = arguments[0];
const d = document, w = window;
const vw = d.documentElement.clientWidth;
const sw = d.documentElement.scrollWidth;

// --- 자체 검증 1: 탐지기가 살아 있는가 -------------------------------------
const bad = d.createElement('div');
bad.style.cssText = 'width:' + (want + 800) + 'px;height:3px';
d.body.appendChild(bad);
const detectorWorks = d.documentElement.scrollWidth > vw + 1;
bad.remove();

// --- 자체 검증 2: Tailwind 가 붙었는가 -------------------------------------
const probe = d.createElement('div');
probe.className = 'rounded-xl';
d.body.appendChild(probe);
const cssApplied = w.getComputedStyle(probe).borderRadius !== '0px';
probe.remove();

// --- 넘침: 스크롤 조상이 없는 것만 센다 ------------------------------------
function scrollAncestor(el) {
  let p = el.parentElement;
  while (p && p !== d.documentElement) {
    const ox = w.getComputedStyle(p).overflowX;
    if (ox === 'auto' || ox === 'scroll') return true;
    p = p.parentElement;
  }
  return false;
}
const real = [], contained = [];
for (const el of d.querySelectorAll('*')) {
  const r = el.getBoundingClientRect();
  if (!(r.width > 0 && r.height > 0)) continue;
  if (!(r.right > vw + 1 || r.left < -1)) continue;
  const rec = { tag: el.tagName, cls: String(el.className).slice(0, 46),
                right: Math.round(r.right), width: Math.round(r.width),
                text: (el.textContent || '').trim().slice(0, 24) };
  (scrollAncestor(el) ? contained : real).push(rec);
}

// --- 잘린 콘텐츠: 스크롤 컨테이너가 아닌데 내용이 넘쳐 hidden 으로 잘린다 ----
const clipped = [];
for (const el of d.querySelectorAll('*')) {
  const cs = w.getComputedStyle(el);
  if (cs.overflowX !== 'hidden') continue;
  if (cs.textOverflow === 'ellipsis') continue;      // 말줄임은 의도된 것
  // ★ sr-only 를 잘린 콘텐츠로 세지 않는다.
  //   Tailwind 의 `sr-only` 는 width:1px/height:1px + overflow:hidden + clip 이다.
  //   스크린리더 전용 알림(이 저장소는 Sprint 223 에서 일부러 넣었다)이라
  //   "내용이 잘렸다"가 아니라 **의도된 시각적 숨김**이다.
  //   실측(2026-08-21): 이 예외가 없으면 /search 와 / 가 매 폭에서 거짓 결함을 낸다
  //   (SearchScreen.tsx 의 <p class="sr-only" role="status">, scrollWidth 141 vs clientWidth 1).
  const r0 = el.getBoundingClientRect();
  if (r0.width <= 1 || r0.height <= 1) continue;
  if (cs.clip && cs.clip !== 'auto') continue;
  if (cs.clipPath && cs.clipPath !== 'none') continue;
  if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
    clipped.push({ tag: el.tagName, cls: String(el.className).slice(0, 40),
                   sw: el.scrollWidth, cw: el.clientWidth,
                   text: (el.textContent || '').trim().slice(0, 24) });
  }
}

// --- 자식이 **부모**를 넘치는가 ---------------------------------------------
//
// ★ 뷰포트 기준만 보면 놓친다. Sprint 240 의 목록 카드 결함이 정확히 그랬다 —
//   grid 컨테이너는 273px 인데 트랙이 277.6px 라 카드가 자기 컨테이너를 넘겼지만,
//   카드 오른쪽 끝(293.6)은 여전히 뷰포트(305) 안이라 "뷰포트 밖" 검사에 안 걸렸다.
//   실측으로 확인하고 이 검사를 추가했다(2026-08-21).
//
//   오탐을 피하려고 제외하는 것들:
//     - 스크롤 컨테이너(넘치라고 만든 것이다)
//     - absolute/fixed 자식(부모 박스와 무관하게 배치된다)
//     - transform 이 걸린 요소(시각적 위치가 레이아웃과 다르다)
//     - 음수 마진(sr-only 의 margin:-1px 같은 의도된 이동)
const parentOverflow = [];
for (const el of d.querySelectorAll('div,section,main,ul,ol,form,header,nav')) {
  const cs = w.getComputedStyle(el);
  if (cs.overflowX === 'auto' || cs.overflowX === 'scroll' || cs.overflowX === 'hidden') continue;
  const pr = el.getBoundingClientRect();
  if (pr.width <= 0) continue;
  const padR = parseFloat(cs.paddingRight) || 0;
  const limit = pr.right - padR + 1;
  for (const ch of el.children) {
    const ccs = w.getComputedStyle(ch);
    if (ccs.position === 'absolute' || ccs.position === 'fixed') continue;
    if (ccs.transform && ccs.transform !== 'none') continue;
    if ((parseFloat(ccs.marginLeft) || 0) < 0 || (parseFloat(ccs.marginRight) || 0) < 0) continue;
    const cr = ch.getBoundingClientRect();
    if (cr.width <= 0 || cr.height <= 0) continue;
    if (cr.right > limit) {
      parentOverflow.push({ parent: el.tagName + '.' + String(el.className).slice(0, 34),
                            child: ch.tagName + '.' + String(ch.className).slice(0, 28),
                            over: Math.round(cr.right - limit + 1),
                            pw: Math.round(pr.width), cw: Math.round(cr.width) });
      break;                       // 부모당 한 건이면 충분하다
    }
  }
}

// --- 이미지 ---------------------------------------------------------------
const imgs = [...d.querySelectorAll('img')];
const imgBroken = imgs.filter(i => i.complete && i.naturalWidth === 0).length;
const imgOverflow = imgs.filter(i => {
  const r = i.getBoundingClientRect();
  return r.width > 0 && r.right > vw + 1 && !scrollAncestor(i);
}).length;

// --- 접근성 ---------------------------------------------------------------
function accName(el) {
  const al = el.getAttribute('aria-label'); if (al && al.trim()) return al.trim();
  const lb = el.getAttribute('aria-labelledby');
  if (lb) {
    const t = lb.split(/\s+/).map(id => { const n = d.getElementById(id); return n ? n.textContent : ''; }).join(' ').trim();
    if (t) return t;
  }
  if (el.labels && el.labels.length) return [...el.labels].map(l => l.textContent).join(' ').trim();
  const ti = el.getAttribute('title'); if (ti && ti.trim()) return ti.trim();
  const ph = el.getAttribute('placeholder'); if (ph && ph.trim()) return ph.trim();
  return (el.textContent || '').trim();
}
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([type=hidden]):not([disabled]),select:not([disabled]),textarea:not([disabled]),[role=button],[tabindex]:not([tabindex="-1"])';
const focusables = [...d.querySelectorAll(FOCUSABLE)]
  .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
const noName = focusables.filter(e => !accName(e))
  .map(e => e.tagName + '.' + String(e.className).slice(0, 30));

// 버튼이 화면 밖으로 밀려 **누를 수 없는가** (스크롤 컨테이너 안이면 접근 가능하다)
const unreachable = focusables.filter(e => {
  const r = e.getBoundingClientRect();
  return (r.right > vw + 1 || r.left < -1) && !scrollAncestor(e);
}).map(e => e.tagName + ':' + accName(e).slice(0, 18));

// 폼 컨트롤 라벨
const formNoLabel = [...d.querySelectorAll('input:not([type=hidden]),select,textarea')]
  .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
  .filter(e => !(e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || (e.labels && e.labels.length)))
  .map(e => e.tagName + '[' + (e.type || '') + ']');

// 헤딩 구조 / 랜드마크
const hs = [...d.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h => +h.tagName[1]);
const headingSkips = [];
for (let i = 1; i < hs.length; i++) if (hs[i] - hs[i - 1] > 1) headingSkips.push(hs[i - 1] + '>' + hs[i]);

return {
  innerWidth: w.innerWidth, vw: vw, scrollWidth: sw,
  pageHScroll: sw > vw + 1,
  detectorWorks: detectorWorks, cssApplied: cssApplied,
  mqSm: w.matchMedia('(min-width: 640px)').matches,
  mqMd: w.matchMedia('(min-width: 768px)').matches,
  mqXl: w.matchMedia('(min-width: 1280px)').matches,
  realOverflow: real.length, realSample: real.slice(0, 5),
  parentOverflow: parentOverflow.length, parentSample: parentOverflow.slice(0, 4),
  containedOverflow: contained.length,
  clipped: clipped.length, clippedSample: clipped.slice(0, 3),
  imgs: imgs.length, imgBroken: imgBroken, imgOverflow: imgOverflow,
  focusables: focusables.length, missingAccName: noName,
  unreachable: unreachable, formNoLabel: formNoLabel,
  h1: d.querySelectorAll('h1').length, headingSkips: headingSkips,
  landmarks: [...new Set([...d.querySelectorAll('header,nav,main,footer')].map(e => e.tagName.toLowerCase()))],
  posTabIndex: focusables.filter(e => e.tabIndex > 0).length,
  path: d.location.pathname,
  nodes: d.body.querySelectorAll('*').length
};
"""

FOCUS_JS = r"""
// 실제 Tab 키를 흉내낼 수 없으므로, 첫 포커스 가능 요소에 focus() 를 준 뒤
// **:focus-visible 규칙이 CSS 에 존재하는지**와 전역 outline:none 제거 여부를 본다.
// (진짜 Tab 판정은 사람이 하는 세션에서만 가능하다 — 여기서는 '지워졌는가'만 잠근다)
const d = document;
let fvRules = 0, globalOutlineNone = 0;
for (const ss of d.styleSheets) {
  let rules; try { rules = ss.cssRules; } catch (e) { continue; }
  for (const r of rules) {
    const t = r.cssText || '';
    if (t.includes(':focus-visible')) fvRules++;
    if (/^\s*\*[^{]*\{[^}]*outline:\s*none/.test(t)) globalOutlineNone++;
  }
}
return { focusVisibleRules: fvRules, globalOutlineNone: globalOutlineNone };
"""


class DriverUnavailable(RuntimeError):
    """브라우저를 띄우지 못했다. **결함이 아니라 측정 불가**다 (종료코드 2).

    이 예외를 따로 두는 이유는 BUGS #188 과 같다 - "모른다"와 "고장났다"를 같은
    값으로 뭉개면, 환경 문제 하나가 제품 결함으로 보고된다.
    """


def _chrome_options(headed: bool, width: int, height: int):
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    if not headed:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    # ★ `--hide-scrollbars` 를 쓰지 않는다.
    #   숨기면 clientWidth 가 요청 폭 그대로가 되어(320) 좁은 데스크톱 창의 실제
    #   가용 폭(320 - 스크롤바 15 = 305)보다 넓어진다. 실측(2026-08-21)에서
    #   그 15px 차이가 Sprint 240 결함의 재현 여부를 갈랐다:
    #       숨김   vw=320 컨테이너 288 트랙 288 -> 안 넘친다(결함이 안 보인다)
    #       안숨김 vw=305 컨테이너 273 트랙 277.6 -> 넘친다(결함이 보인다)
    opts.add_argument("--window-size=%d,%d" % (width, height))
    return opts


def _via_selenium_manager(headed, width, height):
    """Selenium 4.6+ 에 내장된 드라이버 해석기. 캐시에 맞는 드라이버가 있으면
    바깥 네트워크를 타지 않는다."""
    from selenium import webdriver
    return webdriver.Chrome(options=_chrome_options(headed, width, height))


def _via_webdriver_manager(headed, width, height):
    """예전 경로. 버전 확인을 위해 매번 googlechromelabs.github.io 를 두드린다."""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()),
                            options=_chrome_options(headed, width, height))


# ★ 순서에 이유가 있다 (2026-08-25, docs/BUGS.md #193).
#
#   예전에는 `webdriver_manager` **하나뿐**이었다. 그것은 실행할 때마다
#   googlechromelabs.github.io 에서 최신 버전 목록을 받아 온다 - 즉 **바깥 네트워크가
#   되어야만** 이 도구가 돈다. 2026-08-25 이 PC 에서 실제로 그것이 깨졌다:
#
#       requests(= webdriver_manager 가 쓰는 경로) -> SSLCertVerificationError
#                                                    "unable to get local issuer certificate"
#       stdlib urllib 로 같은 URL                  -> HTTP 200, 0.05초
#
#   즉 **오프라인이 아니다.** 그런데 webdriver_manager 는 그 예외를 삼키고
#   "Could not reach host. Are you offline?" 로 바꿔 던졌고, `audit_contrast.py` 는
#   그것을 그대로 40줄짜리 트레이스백으로 토했다. 판정문은 한 줄도 없었다.
#
#   Selenium Manager 는 같은 순간에 9.6초 만에 크롬 151.0.7922.170 을 띄웠다.
#   그래서 **먼저 시도한다.** 실패하면 예전 경로로 떨어지고, 둘 다 실패하면
#   두 이유를 **함께** 들고 DriverUnavailable 로 올린다 - 어느 쪽이 왜 안 됐는지
#   모르면 고칠 수 없기 때문이다.
DRIVER_FACTORIES = (
    ("Selenium Manager", _via_selenium_manager),
    ("webdriver_manager", _via_webdriver_manager),
)


def build_driver(headed: bool, width: int, height: int, factories=None):
    """드라이버를 띄운다. 전부 실패하면 `DriverUnavailable` 을 올린다(트레이스백 금지).

    `factories` 는 검사용 주입구다 - 실제 브라우저 없이 순서/실패 처리를 검증한다.
    """
    reasons = []
    for name, make in (DRIVER_FACTORIES if factories is None else factories):
        try:
            drv = make(headed, width, height)
        except Exception as exc:
            reasons.append("%s -> %s: %s"
                           % (name, type(exc).__name__, " ".join(str(exc).split())[:160]))
            continue
        drv.set_page_load_timeout(60)
        return drv
    raise DriverUnavailable("; ".join(reasons) if reasons else "시도할 방법이 없다")


class _FakeDriver(object):
    """selftest 전용. 진짜 브라우저를 띄우지 않고 build_driver 의 계약만 확인한다."""

    def __init__(self, tag):
        self.tag = tag
        self.timeout = None

    def set_page_load_timeout(self, secs):
        self.timeout = secs


def selftest() -> int:
    """브라우저도 네트워크도 쓰지 않고 이 도구의 판정 로직을 검증한다.

    회귀 스위트(`test_audit_selftests.py`)가 이것을 돌린다. 실제 측정은 서버와
    브라우저가 필요해 스위트에 넣을 수 없지만, **판정이 공허해지는 것**은 여기서 잡힌다.
    """
    fails = []

    def check(name, cond, detail=""):
        print("[%s] %s%s" % ("PASS" if cond else "FAIL", name,
                             "" if cond else " -- %s" % (detail,)))
        if not cond:
            fails.append(name)

    print("--- verdict(): 측정 불가를 정상으로 뭉개지 않는가 ---")
    base = dict(asked="/", path="/", requested=390, innerWidth=390,
                detectorWorks=True, cssApplied=True, nodes=200,
                pageHScroll=False, scrollWidth=390, vw=390,
                realOverflow=0, realSample=[], parentOverflow=0, parentSample=[],
                clipped=0, clippedSample=[], imgBroken=0, imgOverflow=0,
                missingAccName=[], unreachable=[], formNoLabel=[], posTabIndex=0,
                h1=1, headingSkips=[], landmarks=["main"], globalOutlineNone=0)

    def v(**over):
        r = dict(base)
        r.update(over)
        return verdict(r)[0]

    check("깨끗한 화면은 OK", v() == "OK", v())
    # ★ 아래 넷이 핵심이다 - "재지 못했다"를 OK 로 돌려주면 이 도구 전체가 무의미해진다.
    check("빈 화면(노드 0)은 UNUSABLE", v(nodes=0) == "UNUSABLE", v(nodes=0))
    check("뷰포트가 요청과 다르면 UNUSABLE",
          v(innerWidth=500) == "UNUSABLE", v(innerWidth=500))
    check("넘침 탐지기가 죽었으면 UNUSABLE",
          v(detectorWorks=False) == "UNUSABLE", v(detectorWorks=False))
    check("CSS 가 안 붙었으면 UNUSABLE",
          v(cssApplied=False) == "UNUSABLE", v(cssApplied=False))
    check("로그인으로 튕기면 AUTH(통과가 아니다)",
          v(asked="/search", path="/login") == "AUTH", v(asked="/search", path="/login"))
    check("가로 스크롤은 FAIL", v(pageHScroll=True) == "FAIL", v(pageHScroll=True))
    check("h1 이 0개면 FAIL", v(h1=0) == "FAIL", v(h1=0))
    check("main 랜드마크가 없으면 FAIL",
          v(landmarks=["banner"]) == "FAIL", v(landmarks=["banner"]))
    check("접근이름 없는 버튼은 FAIL",
          v(missingAccName=["button.x"]) == "FAIL", v(missingAccName=["button.x"]))

    print("--- build_driver(): 드라이버 해석 순서와 실패 처리 ---")
    calls = []

    def ok_factory(tag):
        def make(headed, width, height):
            calls.append(tag)
            return _FakeDriver(tag)
        return make

    def bad_factory(tag, exc):
        def make(headed, width, height):
            calls.append(tag)
            raise exc
        return make

    def try_build(factories):
        """예외를 값으로 바꾼다. 이렇게 하지 않으면 회귀가 **트레이스백**으로 나와
        어느 단언이 깨졌는지 알 수 없다 - 이 저장소가 반복해서 당한 '증거 없는 실패'다."""
        try:
            return build_driver(False, 390, 900, factories=factories), None
        except Exception as exc:
            return None, "%s: %s" % (type(exc).__name__, exc)

    del calls[:]
    drv, why = try_build([("A", ok_factory("A")), ("B", ok_factory("B"))])
    check("첫 방법이 되면 두 번째는 부르지 않는다", calls == ["A"], (calls, why))
    check("첫 방법이 돌려준 드라이버를 그대로 쓴다", drv is not None and drv.tag == "A", why or drv)
    check("띄운 드라이버에 페이지 타임아웃을 건다", drv is not None and drv.timeout == 60, why or drv)

    del calls[:]
    drv, why = try_build([("A", bad_factory("A", RuntimeError("깨짐"))),
                          ("B", ok_factory("B"))])
    check("첫 방법이 실패하면 다음 방법으로 넘어간다(폴백이 살아 있다)",
          calls == ["A", "B"], (calls, why))
    check("두 번째가 돌려준 것을 쓴다", drv is not None and drv.tag == "B", why or drv)

    del calls[:]
    err = None
    try:
        build_driver(False, 390, 900,
                     factories=[("A", bad_factory("A", RuntimeError("SSL 실패"))),
                                ("B", bad_factory("B", RuntimeError("경로 없음")))])
    except DriverUnavailable as exc:
        err = str(exc)
    except Exception as exc:            # 다른 예외로 새면 호출부가 트레이스백을 토한다
        err = "WRONG:%s" % type(exc).__name__
    check("전부 실패하면 DriverUnavailable 이다(트레이스백 아님)",
          err is not None and not err.startswith("WRONG:"), err)
    check("실패 사유에 두 방법이 **모두** 들어 있다",
          err is not None and "A ->" in err and "B ->" in err, err)
    check("실패 사유에 원래 메시지가 남는다",
          err is not None and "SSL 실패" in err and "경로 없음" in err, err)

    # 자기 검증: 이 검사가 공허하지 않다 - 일부러 틀린 입력을 넣으면 OK 가 아니어야 한다.
    broken = dict(base)
    broken["nodes"] = 0
    check("자기 검증: 빈 화면은 OK 가 아니다", verdict(broken)[0] != "OK", verdict(broken))

    print()
    if fails:
        print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
        return 1
    print("ALL SELFTESTS PASSED (audit_viewport.py)")
    return 0


def set_viewport(drv, width, height):
    """요청한 폭의 **진짜 뷰포트**를 만든다.

    ★ `set_window_size()` 만으로는 안 된다. Windows Chrome 의 최소 창 폭이 약 500px 라
      320/360/390/430 을 요청해도 창은 500px 로 남는다(2026-08-21 실측: 요청 320 ->
      innerWidth 500). 그 상태로 "넘침 0" 이라고 하면 **재지도 않고 통과시키는 것**이다.

      `Emulation.setDeviceMetricsOverride` 는 DevTools 의 기기 모드가 쓰는 것과 같은
      경로로 레이아웃 뷰포트 자체를 바꾼다 — 미디어쿼리도 그 폭으로 평가된다.
      아래 verdict() 가 `innerWidth == 요청폭` 을 다시 확인하므로, 이 경로가 실패하면
      조용히 통과하지 않고 UNUSABLE 로 떨어진다.
    """
    drv.set_window_size(max(width, 520), height)
    try:
        drv.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height,
            "deviceScaleFactor": 1,
            # ★ `mobile: False` 로 둔다. True 면 오버레이 스크롤바가 되어
            #   clientWidth 가 요청 폭 그대로(320)가 되는데, 그것은 **더 넉넉한** 조건이다.
            #   좁은 데스크톱 창(스크롤바 15px 차지)이 더 빠듯하고, Sprint 240 결함이
            #   드러난 것도 그 조건이었다. 둘 중 **빠듯한 쪽**으로 잠근다 —
            #   여기서 통과하면 모바일(더 넉넉)에서도 통과한다.
            "mobile": False,
        })
    except Exception:
        pass          # 덮어쓰기 실패는 verdict() 의 뷰포트 검증에서 UNUSABLE 로 잡힌다


def measure(drv, base, path, width, height, min_nodes):
    import time
    set_viewport(drv, width, height)
    drv.get(base + path)
    # 클라이언트 렌더가 끝날 때까지 기다린다(노드 수가 하한을 넘을 때까지)
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            n = drv.execute_script("return document.body ? document.body.querySelectorAll('*').length : 0")
            if n >= min_nodes:
                break
        except Exception:
            pass
        time.sleep(0.3)
    time.sleep(1.2)
    r = drv.execute_script(MEASURE_JS, width)
    r.update(drv.execute_script(FOCUS_JS))
    r["requested"] = width
    r["asked"] = path.split("?")[0]
    return r


def verdict(r):
    """(상태, 사유목록). 상태: OK / FAIL / AUTH / UNUSABLE"""
    if r["asked"] != "/" and r["path"] != r["asked"]:
        return "AUTH", ["요청 %s -> 도착 %s (로그인 필요, 측정 대상 아님)" % (r["asked"], r["path"])]
    problems = []
    # --- 측정 자체가 믿을 만한가 ---
    if abs(r["innerWidth"] - r["requested"]) > 20:
        return "UNUSABLE", ["뷰포트가 요청과 다르다 %d != %d" % (r["innerWidth"], r["requested"])]
    if not r["detectorWorks"]:
        return "UNUSABLE", ["넘침 탐지기가 동작하지 않는다(self-test 실패)"]
    if not r["cssApplied"]:
        return "UNUSABLE", ["Tailwind 가 적용되지 않았다 - 넘침 0 이 무의미하다"]
    if r["nodes"] < 15:
        return "UNUSABLE", ["화면이 그려지지 않았다(노드 %d)" % r["nodes"]]
    # --- 진짜 결함 ---
    if r["pageHScroll"]:
        problems.append("페이지 가로 스크롤 (scrollWidth %d > clientWidth %d)"
                        % (r["scrollWidth"], r["vw"]))
    if r["realOverflow"]:
        problems.append("뷰포트 밖 요소 %d개: %s" % (r["realOverflow"],
                        "; ".join("%s.%s r=%d" % (s["tag"], s["cls"], s["right"])
                                  for s in r["realSample"][:3])))
    if r.get("parentOverflow"):
        problems.append("부모 박스를 넘는 자식 %d개: %s" % (r["parentOverflow"],
                        "; ".join("%s > %s (+%dpx, 부모 %d / 자식 %d)"
                                  % (s2["parent"], s2["child"], s2["over"], s2["pw"], s2["cw"])
                                  for s2 in r["parentSample"][:2])))
    if r["clipped"]:
        problems.append("잘린 콘텐츠 %d개: %s" % (r["clipped"],
                        "; ".join("%s(%d>%d)" % (s["tag"], s["sw"], s["cw"])
                                  for s in r["clippedSample"])))
    if r["imgBroken"]:
        problems.append("깨진 이미지 %d개" % r["imgBroken"])
    if r["imgOverflow"]:
        problems.append("화면을 넘는 이미지 %d개" % r["imgOverflow"])
    if r["missingAccName"]:
        problems.append("접근이름 없는 조작요소 %d개: %s"
                        % (len(r["missingAccName"]), r["missingAccName"][:3]))
    if r["unreachable"]:
        problems.append("화면 밖이라 누를 수 없는 요소 %d개: %s"
                        % (len(r["unreachable"]), r["unreachable"][:3]))
    if r["formNoLabel"]:
        problems.append("라벨 없는 폼 컨트롤 %d개: %s" % (len(r["formNoLabel"]), r["formNoLabel"][:3]))
    if r["posTabIndex"]:
        problems.append("양수 tabindex %d개(탭 순서 조작)" % r["posTabIndex"])
    if r["h1"] != 1:
        problems.append("h1 이 %d개(정확히 1개여야 한다)" % r["h1"])
    if r["headingSkips"]:
        problems.append("헤딩 단계 건너뜀 %s" % r["headingSkips"])
    if "main" not in r["landmarks"]:
        problems.append("main 랜드마크가 없다 (%s)" % r["landmarks"])
    if r["globalOutlineNone"]:
        problems.append("전역 outline:none %d건(포커스 표시 제거)" % r["globalOutlineNone"])
    return ("FAIL" if problems else "OK"), problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("VIEWPORT_BASE", BASE_DEFAULT))
    ap.add_argument("--width", type=int, action="append")
    ap.add_argument("--headed", action="store_true")
    # ★ 로그인 화면을 재려면 세션이 필요하다. 이 도구는 **자격증명을 다루지 않는다** —
    #   이미 로그인된 브라우저의 쿠키를 그대로 받아 붙일 뿐이다.
    #   얻는 법: 로그인한 탭의 DevTools 콘솔에서 `document.cookie` 를 복사.
    #       python audit_viewport.py --cookie "sb-xxx-auth-token=base64-..."
    #   주지 않으면 그 화면들은 AUTH(측정 안 함)로 남는다 - 통과로 세지 않는다.
    ap.add_argument("--cookie", help="로그인된 브라우저의 document.cookie 문자열")
    ap.add_argument("--json", help="결과를 이 경로에 JSON 으로 남긴다")
    # 브라우저도 서버도 네트워크도 쓰지 않는다 - 회귀 스위트가 이것만 돌린다
    # (test_audit_selftests.py). 2026-08-25 신설, docs/BUGS.md #193.
    ap.add_argument("--selftest", action="store_true",
                    help="판정 로직만 검사한다(브라우저/서버 불필요)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    widths = args.width or WIDTHS_DEFAULT

    # 서버부터 확인한다 — 없는데 "넘침 0" 이라고 말하지 않기 위해서다.
    import urllib.request
    try:
        urllib.request.urlopen(args.base, timeout=8).read(1)
    except Exception as e:
        print("WEB 서버(%s)에 연결할 수 없다: %s" % (args.base, e))
        print("먼저 `npm run dev` 로 띄운 뒤 다시 실행하라. (측정 불가 = 종료코드 2)")
        return 2

    screens = list(SCREENS)
    driver = None
    try:
        driver = build_driver(args.headed, widths[0], 900)
    except DriverUnavailable as e:
        # 시도한 방법이 각각 왜 실패했는지 **전부** 찍는다. 하나만 찍으면
        # 네트워크 문제와 크롬 부재를 구별할 수 없다 (docs/BUGS.md #193).
        print("브라우저를 띄우지 못했다 - 시도한 방법과 사유:")
        for reason in str(e).split("; "):
            print("    %s" % reason)
        print("(측정 불가 = 종료코드 2. 정상으로 뭉개지 않는다.)")
        return 2
    except Exception as e:
        print("브라우저를 띄우지 못했다: %s: %s" % (type(e).__name__, str(e)[:200]))
        print("(측정 불가 = 종료코드 2. 정상으로 뭉개지 않는다.)")
        return 2

    if args.cookie:
        # 쿠키는 도메인 컨텍스트가 있어야 심을 수 있다 - 먼저 그 도메인을 연다.
        try:
            driver.get(args.base + "/login")
            import time as _t
            _t.sleep(1)
            planted = 0
            for part in args.cookie.split(";"):
                part = part.strip()
                if "=" not in part:
                    continue
                name, value = part.split("=", 1)
                try:
                    driver.add_cookie({"name": name.strip(), "value": value.strip(), "path": "/"})
                    planted += 1
                except Exception:
                    pass
            print("쿠키 %d개를 심었다(로그인 화면도 측정한다)" % planted)
        except Exception as e:
            print("쿠키 주입 실패: %s (로그인 화면은 AUTH 로 남는다)" % str(e)[:80])

    results, fails, unusable, auth = [], 0, 0, 0
    try:
        # ── 검색 결과 카드가 실제로 그려지는 조건을 찾는다 ──────────────────────
        #
        # 카드가 0장인 목록을 재고 "넘침 0"이라고 말하면 그것은 측정이 아니다.
        # 기본 조건 -> 종결 포함 순으로 시도하고, **카드가 나온 조건으로 검색 화면을
        # 바꿔 잰다.** 어느 쪽에서도 카드가 없으면 정상으로 세지 않고 측정 불가로 센다.
        no_cards = False
        if DETAIL_FROM_SEARCH:
            hrefs, used = [], None
            for cand in (SEARCH_PATH, SEARCH_PATH_WITH_CLOSED):
                try:
                    driver.get(args.base + cand)
                    import time as _t
                    _t.sleep(3)
                    hrefs = driver.execute_script(
                        "return [...document.querySelectorAll('a')]"
                        ".map(x=>x.getAttribute('href')||'')"
                        ".filter(h=>/^\\/properties\\/\\d+/.test(h))"
                        ".map(h=>h.split('?')[0]);") or []
                except Exception as e:
                    print("검색 표본 수집 실패(%s): %s" % (cand, str(e)[:60]))
                    hrefs = []
                if hrefs:
                    used = cand
                    break
            if used and used != SEARCH_PATH:
                screens = [(used, 200) if p == SEARCH_PATH else (p, n) for p, n in screens]
                print("검색 결과가 0건이라 `include_closed=true` 로 바꿔 잰다"
                      " (카드 %d장) - 이 DB 는 기일이 남은 물건이 없다" % len(hrefs))
            if hrefs:
                screens.append((hrefs[0], 60))
                print("상세 표본: %s (카드 %d장)" % (hrefs[0], len(hrefs)))
            else:
                no_cards = True
                print("★ 결과 카드가 어느 조건에서도 0장이다"
                      " - 목록 카드와 상세를 **재지 못했다**(측정 불가로 센다)")

        print("=" * 86)
        print(" 실제 뷰포트 레이아웃/접근성 감사  base=%s" % args.base)
        print("=" * 86)
        for path, min_nodes in screens:
            for w in widths:
                try:
                    r = measure(driver, args.base, path, w, 900, min_nodes)
                except Exception as e:
                    print("  %-34s %5d  측정 실패: %s" % (path[:34], w, str(e)[:50]))
                    unusable += 1
                    continue
                st, why = verdict(r)
                results.append({"path": path, "width": w, "status": st,
                                "problems": why, "raw": r})
                mark = {"OK": "OK  ", "FAIL": "FAIL", "AUTH": "AUTH", "UNUSABLE": "????"}[st]
                extra = ""
                if st == "OK":
                    extra = ("vw=%d sw=%d 넘침0 컨테이너내%d 이미지%d md=%s"
                             % (r["vw"], r["scrollWidth"], r["containedOverflow"],
                                r["imgs"], r["mqMd"]))
                else:
                    extra = "; ".join(why)[:110]
                print("  [%s] %-34s %5dpx  %s" % (mark, path[:34], w, extra))
                if st == "FAIL":
                    fails += 1
                elif st == "UNUSABLE":
                    unusable += 1
                elif st == "AUTH":
                    auth += 1
    finally:
        try: driver.quit()
        except Exception: pass

    print()
    print("=" * 86)
    if no_cards:
        # 재지 못한 화면을 집계에서 생략하면 합계가 "결함 0"으로 읽힌다.
        # 목록 카드와 상세 둘 다 폭마다 못 재으므로 그만큼을 측정 불가로 센다.
        unusable += 2 * len(widths)
    ok = sum(1 for r in results if r["status"] == "OK")
    print(" 정상 %d / 결함 %d / 로그인필요(측정안함) %d / 측정불가 %d"
          % (ok, fails, auth, unusable))
    if auth:
        print(" ※ 로그인 필요 화면은 **통과로 세지 않았다.** 헤드리스에는 세션이 없어")
        print("    /login 으로 튕기며, 그 단순한 화면은 당연히 넘치지 않는다.")
        print("    그 화면들은 로그인된 브라우저 세션에서 따로 봐야 한다.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
        print(" JSON: %s" % args.json)
    if unusable:
        print(" 측정 불가가 있어 종료코드 2 (정상으로 뭉개지 않는다)")
        return 2
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
