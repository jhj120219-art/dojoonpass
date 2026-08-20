"""프런트 접근성 — 실측 기준선 고정 (2026-08-19 Sprint 219 신설).

## 왜 이 파일이 있나

이 서비스의 사용자에는 **어르신이 포함된다**(docs/roadmap.md "큰글씨 기능").
그런데 화면의 핵심 정보가 얼마나 읽기 어려운지 **아무도 재 본 적이 없었다.**

실브라우저(`/search`, Chrome)로 직접 쟀다. 2026-08-19 실측:

    검사한 텍스트                    199개
    WCAG AA 대비(4.5:1) 미달          81개  (41%)
    text-gray-400 on white 실제 대비   2.6:1   <- 기준의 58%
    탭 타깃 53개 중 44px 미만          44개  (83%)
    그중 **24px 미만**                  5개   <- ★ 위반 아님(2026-08-20 Sprint 225)
                                             간격(Spacing) 예외로 적합. 중심 간 54px vs 임계 24px
    14px 미만 텍스트                  111개

가장 나쁜 것은 **무엇이** 작고 흐린가이다.

    물건 주소          12px / 2.6:1
    "최저입찰가" 라벨   11px / 2.6:1
    "감정가 3.8억"     11px / 2.6:1
    24px 미만 탭 타깃   헤더 내비 5개(검색/최근 본 물건/관심물건/마이페이지/로그아웃), 전부 h=16px

즉 **가격과 주소** — 이 서비스를 쓰는 이유 그 자체 — 가 화면에서 가장 읽기 어렵다.

## ★ 측정 도구가 한 번 틀렸다 (기록으로 남긴다)

처음 만든 대비 계산기는 CSS 색 문자열에서 숫자만 뽑아 RGB 로 읽었다. 그런데
이 저장소의 Tailwind v4 는 **`oklch()`** 로 색을 낸다 — `oklch(0.546 0.245 262.881)`
을 RGB [0.546, 0.245, 262.881] 로 읽어 **대비 1.06 같은 불가능한 값**을 뱉었다.
그대로 보고했으면 멀쩡한 색을 결함으로 올릴 뻔했다.

canvas 로 브라우저에게 변환을 시키고, **알려진 값으로 도구부터 검증**한 뒤 다시 쟀다
(흑백 21.0 / `#9ca3af` on white 2.54 — 둘 다 알려진 정답과 일치).

## 이 검사는 무엇을 하나 — **고치는 게 아니라 잠근다**

큰글씨/접근성 개선은 `docs/roadmap.md` 가 "웹 핵심 기능 안정화 후"로 잡은 항목이고,
글자 크기·색·간격을 바꾸는 것은 **제품 디자인 결정**이다. 여기서 임의로 하지 않는다.

대신 **지금 수치를 상한으로 박아 둔다.** 줄어들면 통과하고(개선은 언제나 환영),
늘어나면 실패한다. `test_schema_hygiene.py` 가 "추적되면 안 되는 파일"에 쓰는
것과 같은 방식이다 — 정리는 나중에 하더라도 **늘어나는 것만은 막는다.**

    python test_frontend_accessibility.py
"""
import glob
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))

failures = []


def emit(line):
    """cp949 콘솔에서 죽지 않게 찍는다(이 저장소의 공통 규약)."""
    try:
        print(line)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(line.encode(enc, "replace").decode(enc, "replace"))


def check(name, actual, expected):
    ok = actual == expected
    emit("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    emit("[%s] %s%s" % ("PASS" if cond else "FAIL", name,
                        "" if cond else " -- " + str(detail)))
    if not cond:
        failures.append(name)


def check_le(name, actual, ceiling):
    """상한 검사 — 줄어들면 통과, 늘어나면 실패."""
    ok = actual <= ceiling
    emit("[%s] %s: %d (상한 %d%s)"
         % ("PASS" if ok else "FAIL", name, actual, ceiling,
            ", 줄었다" if actual < ceiling else ""))
    if not ok:
        failures.append(name)


# ---------------------------------------------------------------------------
# 2026-08-19 실측 기준선. **줄이는 것은 자유, 늘리는 것은 막는다.**
#
# 값의 뜻:
#   text-xs        12px. 본문/라벨에 쓰이면 어르신에게 작다
#   text-[11px]    11px 고정. **2026-08-19 Sprint 223에 전부 rem 으로 바꿔 0이 됐다.**
#   text-[10px]    10px 고정. 같은 이유로 0이다.
#   text-[0.6875rem]  11px 와 **같은 크기**이지만 루트 글꼴을 키우면 따라 커진다
#   text-[0.625rem]   10px 과 같은 크기, 역시 rem 기반
#   text-gray-400  흰 배경에서 대비 2.6:1 (WCAG AA 4.5:1 의 58%)
#   text-gray-300  그보다 더 낮다
# ---------------------------------------------------------------------------
# ★ 2026-08-20 Sprint 225 — 상한을 재기준했다. **값이 늘어난 것은 코드가 나빠져서가
#   아니라 이 검사가 그동안 `src/components/` 를 안 보고 있었기 때문이다.**
#
#       src/app        text-xs 111 / text-gray-400 106   <- 예전 상한 (여기까지만 셌다)
#       src/components text-xs   7 / text-gray-400   4   <- **한 번도 세지 않았다**
#       합계           text-xs 118 / text-gray-400 110
#
#   하필 그 사각지대에 `SiteHeader.tsx` 와 `PrimaryNav.tsx` 가 있다 —
#   **Sprint 219 가 "가장 나쁘다"고 지목해 실측한 헤더 내비 바로 그것**이다.
#   즉 문서의 "text-xs 111회 / text-gray-400 106회"는 과소 집계였다.
CEILINGS = {
    "text-xs": 117,
    "text-[11px]": 0,
    "text-[10px]": 0,
    "text-[0.6875rem]": 6,
    "text-[0.625rem]": 2,
    "text-gray-400": 110,
    "text-gray-300": 6,
    # 흰 배경 대비 **2.89:1** (실측 2026-08-20, rgb(255,100,103)). 오류 문구 2곳에
    # 쓰인다 — 하필 **가장 읽혀야 하는 글자**가 본문 회색보다도 잘 안 보인다.
    "text-red-400": 2,
}

PATTERNS = {
    "text-xs": r"\btext-xs\b",
    "text-[11px]": r"text-\[11px\]",
    "text-[10px]": r"text-\[10px\]",
    "text-[0.6875rem]": r"text-\[0\.6875rem\]",
    "text-[0.625rem]": r"text-\[0\.625rem\]",
    "text-gray-400": r"\btext-gray-400\b",
    "text-gray-300": r"\btext-gray-300\b",
    "text-red-400": r"\btext-red-400\b",
}

# 추적 대상 밖의 **더 나쁜 색**으로 갈아타면 이 상한은 오히려 내려간다 —
# 그러면 검사는 초록불인데 화면은 나빠진다(2026-08-20 Sprint 225 실측으로 확인한 구멍).
# 그래서 "쓰이는 낮은 대비 계열을 전부 열거하고, 표에 없는 것이 나타나면 알린다"를 함께 건다.
# 색조는 굳이 제한하지 않는다 — gray 든 slate 든 zinc 든 200~400 단계는 흰 배경에서
# 전부 4.5:1 을 넘지 못한다.
LOW_CONTRAST_SCAN = (
    r"\btext-(?:gray|slate|zinc|neutral|stone|blue|red|green|orange|amber|yellow"
    r"|lime|emerald|teal|cyan|sky|indigo|violet|purple|fuchsia|pink|rose)"
    r"-(?:100|200|300|400)\b"
)


def _strip_comments(src):
    """`/* */`, `//`, JSX `{/* */}` 주석을 지운다(줄 수는 보존한다).

    주석 안의 코드 예시를 실제 코드로 세면 **멀쩡한 파일이 결함으로 잡힌다.**
    실제로 한 번 그랬다 — `ResultThumbnail.tsx` 의 주석이 Next.js 오류 메시지를
    인용하는데 거기 `<img ...>` 가 들어 있다.

    줄 수를 보존하는 이유: 지운 뒤에도 **줄 번호가 원본과 같아야** 보고가 쓸모 있다.
    """
    def blank(m):
        return re.sub(r"[^" + chr(92) + "n]", " ", m.group(0))
    src = re.sub(r"/" + chr(92) + "*[" + chr(92) + "s" + chr(92) + "S]*?" + chr(92) + "*/", blank, src)
    src = re.sub(r"//[^" + chr(92) + "n]*", blank, src)
    return src


def _tsx_files():
    """화면(`src/app`) **과 공용 컴포넌트(`src/components`)** 의 모든 `.tsx`.

    목록을 손으로 적지 않는다 — 새 화면/새 컴포넌트가 생기면 다음 실행부터 대상이 된다.

    ★ 2026-08-20 Sprint 225: `src/components` 가 빠져 있었다. 화면 파일만 세면
      **공용 컴포넌트로 옮긴 순간 그 글자는 검사에서 사라진다** — 리팩터링이
      곧 검사 회피가 된다. 실제로 `SiteHeader.tsx`/`PrimaryNav.tsx` 의
      `text-xs` 7개와 `text-gray-400` 4개가 한 번도 세어지지 않았고,
      그것이 하필 Sprint 219 가 "가장 나쁘다"고 지목한 헤더 내비였다.
      (Sprint 224 에 `ResultThumbnail.tsx` 를 그쪽으로 옮기면서 드러났다.)
    """
    out = []
    for sub in ("app", "components"):
        out += glob.glob(os.path.join(ROOT, "src", sub, "**", "*.tsx"), recursive=True)
    return sorted(out)


def test_small_and_low_contrast_text_does_not_grow():
    emit("\n--- 1. 작은 글자 / 낮은 대비 사용이 늘지 않는가 (상한 고정) ---")
    files = _tsx_files()

    # 열거가 깨지면 0개를 훑고 조용히 통과한다 — 하한을 함께 건다(TEST_PLAN 규칙).
    check_true("화면 소스를 실제로 찾았다(검사가 공허하지 않다)", len(files) >= 12, len(files))

    counts = {k: 0 for k in PATTERNS}
    per_file = {}
    for path in files:
        # ★ 2026-08-20 Sprint 227 - **주석을 코드로 세고 있었다.**
        #   이 파일은 `_strip_comments()` 를 이미 갖고 있고 형제 검사들은 쓰는데,
        #   정작 상한 계수기만 원문을 그대로 셌다. 그래서
        #     - 클래스 이름을 **설명하는 주석**이 사용 횟수로 잡히고
        #       (실제로 이 스프린트에서 `text-sm 을 쓴 이유` 를 적었더니 상한을 넘겼다),
        #     - 반대로 주석을 지우면 상한에 여유가 생겨 **진짜 사용이 늘어도 통과**한다.
        #   저장소 규칙("주석/문자열을 실제 코드로 세지 않는다")을 계수기만 어기고 있었다.
        src = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        hit = {}
        for name, rx in PATTERNS.items():
            n = len(re.findall(rx, src))
            counts[name] += n
            if n:
                hit[name] = n
        if hit:
            per_file[rel] = hit

    for name in sorted(CEILINGS):
        check_le("%s 사용 횟수" % name, counts[name], CEILINGS[name])

    # ★ 표에 없는 저대비 클래스가 나타나면 알린다. 상한만 걸면 **추적 밖의 더 나쁜
    #   색으로 갈아타는 것**을 막지 못한다(상한은 오히려 내려가 초록불이 된다).
    seen = set()
    for path in files:
        src = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        seen |= set(re.findall(LOW_CONTRAST_SCAN, src))
    untracked = sorted(seen - set(CEILINGS))
    check_true("추적 밖의 저대비 클래스가 없다", not untracked,
               "표(CEILINGS)에 없다 - 대비를 재고 등록하거나 쓰지 않는다: %s" % untracked)
    # 스캔 자체가 죽으면 위 검사가 공허하게 통과한다 — 하한을 건다.
    check_true("저대비 클래스 스캔이 실제로 동작했다(검사가 공허하지 않다)",
               len(seen) >= 2, sorted(seen))

    emit("    파일 %d개 / 사용처 상위:" % len(files))
    for rel, hit in sorted(per_file.items(), key=lambda kv: -sum(kv[1].values()))[:5]:
        emit("      %-44s %s" % (rel, hit))


def test_root_font_scaling_reaches_the_text():
    r"""큰글씨 모드가 **닿지 못하는 글자**가 몇 곳인가 (2026-08-19 Sprint 220).

    ## 앞선 기록을 정정한다

    Sprint 219 문서는 *"지금 크기가 대부분 px 고정이라 루트 글꼴만 키워도 본문이
    따라 커지지 않는다"* 고 적었다. **그것은 틀렸다.**

    빌드된 CSS 를 직접 확인했다 — Tailwind v4 의 이름 있는 크기는 **rem 기반**이다.

        --text-xs: .75rem      .text-xs  { font-size: var(--text-xs) }
        --text-sm: .875rem     .text-sm  { font-size: var(--text-sm) }

    즉 루트 `font-size` 를 키우면 `text-xs`(111곳 사용) 는 **그대로 따라 커진다.**
    닿지 않는 것은 **대괄호 임의값**뿐이다.

    실측(2026-08-19): 임의 px 값 전체 10곳 중 **글자 크기는 8곳**
    (`text-[11px]` 6 + `text-[10px]` 2). 나머지 2곳(`max-h-[420px]`,
    `max-w-[180px]`)은 상한이라 글자 크기와 무관하다.

    ## 그래서 무엇이 달라지나

    큰글씨 모드의 선행 작업은 "전면 rem 전환"이 아니라 **그 8곳을 rem 유틸리티로
    바꾸는 것**이다. 훨씬 작은 일이다. 이 검사는 그 8곳이 **늘어나지 않게** 잠근다 —
    늘어나면 큰글씨가 닿지 못하는 자리가 그만큼 늘어난다.
    """
    emit(chr(10) + "--- 6. 루트 글꼴 확대가 닿지 않는 글자 ---")
    files = _tsx_files() + sorted(glob.glob(os.path.join(ROOT, "src", "components", "*.tsx")))
    check_true("화면 소스를 실제로 찾았다", len(files) >= 12, len(files))

    font_px, other_px = [], []
    for path in files:
        code = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        for m in re.finditer(r"[\w:-]*\[\d+(?:\.\d+)?px\]", code):
            tok = m.group(0)
            rec = "%s:%d %s" % (rel, code[:m.start()].count(chr(10)) + 1, tok)
            (font_px if tok.startswith("text-") else other_px).append(rec)

    # 상한 0곳. 2026-08-19 Sprint 223에 8곳을 전부 rem 으로 바꿔 **하나도 안 남았다.**
    # 이제는 한 곳이라도 생기면 즉시 걸린다.
    check_le("큰글씨가 닿지 않는 글자 크기(임의 px)", len(font_px), 0)
    emit("    글자 크기 임의 px %d곳 / 그 외 임의 px %d곳(상한이라 무관)"
         % (len(font_px), len(other_px)))
    for r in sorted(font_px)[:8]:
        emit("      %s" % r)

    # ★ 이 검사가 공허하지 않으려면 **rem 기반이라는 전제 자체**를 확인해야 한다.
    #   빌드 CSS 에서 Tailwind 의 크기 토큰이 rem 인지 직접 본다. 없으면 건너뛰되
    #   "확인하지 못했다"고 말한다(통과로 위장하지 않는다).
    css_files = glob.glob(os.path.join(ROOT, ".next", "**", "*.css"), recursive=True)
    rem_seen = None
    for c in sorted(css_files, key=os.path.getsize, reverse=True):
        body = io.open(c, encoding="utf-8", errors="replace").read()
        m = re.search(r"--text-xs:\s*([^;]+);", body)
        if m:
            rem_seen = m.group(1).strip()
            break
    if rem_seen is None:
        emit("    [미확인] 빌드 CSS 가 없어 rem 전제를 확인하지 못했다 (npm run build 후 재실행)")
    else:
        check_true("Tailwind 크기 토큰이 rem 기반이다(큰글씨의 전제)",
                   rem_seen.endswith("rem"), rem_seen)
        emit("    --text-xs = %s" % rem_seen)

def test_zoom_is_not_disabled():
    """확대를 막는 뷰포트 설정이 없어야 한다.

    `user-scalable=no` / `maximum-scale=1` 은 **어르신이 두 손가락으로 키우는 것을
    막는다.** 지금은 없다(Next.js 기본 `width=device-width, initial-scale=1`).
    없다는 사실을 고정해 둔다 — 나중에 "레이아웃이 흔들려서" 넣고 싶어지는 자리다.
    """
    emit("\n--- 2. 확대를 막지 않는가 ---")
    layout = os.path.join(ROOT, "src", "app", "layout.tsx")
    check_true("layout.tsx 가 있다", os.path.exists(layout), layout)
    src = io.open(layout, encoding="utf-8-sig").read() if os.path.exists(layout) else ""

    banned = [t for t in ("user-scalable=no", "user-scalable=0", "userScalable: false",
                          "maximumScale: 1", "maximum-scale=1") if t in src]
    check("확대 차단 설정", banned, [])

    # 전체 소스에도 없어야 한다(어느 화면이든 넣을 수 있다).
    everywhere = []
    for path in _tsx_files():
        body = io.open(path, encoding="utf-8-sig").read()
        for t in ("user-scalable=no", "userScalable: false", "maximumScale: 1"):
            if t in body:
                everywhere.append(os.path.relpath(path, ROOT))
    check("어느 화면에도 확대 차단이 없다", sorted(set(everywhere)), [])


def test_list_and_detail_keep_semantic_alt_rules():
    """사진에 대한 대체 텍스트 규약이 유지되는가.

    검색목록 썸네일은 **장식**이다 — 물건 정보는 옆 텍스트가 전부 담고 있다.
    그래서 `alt=""` + `aria-hidden` 이 맞다(스크린리더가 같은 내용을 두 번 읽지 않는다).
    반대로 `alt` 를 빠뜨리면 스크린리더가 **URL 을 읽는다** — 그건 결함이다.
    """
    emit("\n--- 3. 사진의 대체 텍스트 규약 ---")
    # 2026-08-20 Sprint 224: 검색목록 전용이 아니게 되어(관심물건/최근 본 물건도 쓴다)
    # src/components/ 로 옮겼다. 경로를 손으로 적는 검사는 이렇게 같이 옮겨야 한다.
    thumb = os.path.join(ROOT, "src", "components", "ResultThumbnail.tsx")
    check_true("ResultThumbnail 이 있다", os.path.exists(thumb), thumb)
    if not os.path.exists(thumb):
        return
    src = io.open(thumb, encoding="utf-8-sig").read()
    check_true('썸네일은 alt="" 로 장식임을 밝힌다', 'alt=""' in src, src[:200])
    check_true("aria-hidden 으로 스크린리더에서 뺀다", 'aria-hidden' in src, src[:200])
    check_true("깨졌을 때 자리를 남기지 않는다(onError)", "onError" in src, src[:200])

    # `<img` 를 쓰는 화면 전부가 alt 를 갖고 있는가 (빠뜨리면 스크린리더가 URL 을 읽는다)
    #
    # ★ **주석을 먼저 걷어낸다** (2026-08-19). 처음 만든 이 검사는 주석 속 `<img` 를
    #   그대로 잡아 `ResultThumbnail.tsx` 를 결함으로 보고했다 — 그 파일의 주석은
    #   Next.js 오류 메시지(`<img ... onError={function onError} ...>`)를 인용하고
    #   있을 뿐이다. **멀쩡한 코드를 결함으로 올릴 뻔했다.**
    missing = []
    for path in _tsx_files():
        body = io.open(path, encoding="utf-8-sig").read()
        stripped = _strip_comments(body)
        for m in re.finditer(r"<img" + chr(92) + "b", stripped):
            seg = stripped[m.start():m.start() + 400]
            if "alt=" not in seg:
                missing.append("%s:%d" % (os.path.relpath(path, ROOT),
                                          stripped[:m.start()].count(chr(10)) + 1))
    check("alt 가 없는 <img>", sorted(missing), [])

    # 검사기가 눈이 멀지 않았는지 — 주석을 지웠어도 **진짜 <img> 는 남아야 한다**
    real = 0
    for path in _tsx_files():
        real += len(re.findall(r"<img" + chr(92) + "b",
                               _strip_comments(io.open(path, encoding="utf-8-sig").read())))
    check_true("실제 <img> 를 찾았다(주석만 지우고 본문까지 지우지 않았다)",
               real >= 1, real)


def test_no_structural_mobile_overflow():
    r"""모바일에서 **가로로 넘칠 구조**가 없는가 (2026-08-19 Sprint 220).

    ## 왜 소스로 보는가

    실제 모바일 뷰포트로 확인하지 못했다 — 브라우저 자동화의 창 리사이즈가
    페이지 뷰포트에 반영되지 않고(`innerWidth` 1920 고정), 앱이
    `X-Frame-Options: DENY` 라 iframe 으로 좁은 폭을 만드는 우회도 막힌다
    (그 헤더 자체는 올바른 보안 설정이다).

    그렇다고 "모바일 정상"이라고 판정하지 않는다. 대신 **가로 넘침을 일으키는
    구조적 원인**을 전수로 훑어 그것이 0곳임을 고정한다. 이것은
    "넘치지 않는다"의 증명이 아니라 **"넘칠 원인이 없다"의 증명**이다.

    ## 무엇이 원인이 되는가

        고정 폭       w-[420px] / min-w-[360px] / style={{width: 400}}
        뷰포트 폭     w-screen / 100vw  (스크롤바 폭 때문에 실제로 넘친다)
        내용 폭 강제  min-w-max / min-w-fit
        3열 이상 그리드가 반응형 접두사 없이 걸리는 경우
        <table>       열이 줄지 않아 모바일에서 가장 잘 깨진다

    ## 지금 상태 (실측 2026-08-19)

        고정 폭·뷰포트 폭·내용 폭 강제   전부 0곳
        <table>                          0곳
        컨테이너                          max-w-[1320px] mx-auto px-4 md:px-8
                                         (고정 width 가 아니라 **상한** + 모바일 패딩)
        grid                             전부 mobile-first (md:grid-cols-2 xl:grid-cols-3)
        overflow-x-auto 2곳              썸네일 줄 / 정렬 바 — **컨테이너 내부**의 의도된 가로 스크롤
    """
    emit(chr(10) + "--- 5. 모바일 가로 넘침의 구조적 원인이 없는가 ---")
    files = _tsx_files()
    check_true("화면 소스를 실제로 찾았다", len(files) >= 12, len(files))

    # ★ 검출기를 **넣기 전에** 검증한다(2026-08-20 Sprint 225).
    #   이 저장소는 "0곳"이라는 결과가 검출기가 죽어서 나온 것인지 코드가 깨끗해서
    #   나온 것인지 구별하지 못해 여러 번 손해를 봤다. 그래서 고정 폭 정규식을
    #   **반드시 잡아야 하는 예 / 절대 잡으면 안 되는 예**로 먼저 시험한다.
    _FIXED_W = r"(?<!max-)(?<!min-)\bw-\[\d{3,}px\]"
    _MUST_HIT = ['className="w-[420px]"', 'flex w-[1024px] gap-2']
    _MUST_MISS = ['max-w-[1320px] mx-auto', 'max-w-[180px] truncate',
                  'min-w-[360px]', 'w-[80px]', 'w-full']
    check_true("검출기 자체 검증: 고정 폭을 잡는다",
               all(re.search(_FIXED_W, x) for x in _MUST_HIT), _MUST_HIT)
    check_true("검출기 자체 검증: 상한(max-w)·min-w·두 자리 폭을 잡지 않는다",
               not any(re.search(_FIXED_W, x) for x in _MUST_MISS),
               [x for x in _MUST_MISS if re.search(_FIXED_W, x)])

    # ★ 2026-08-20 Sprint 225 — 검출기가 **상한을 고정 폭으로 오인**하고 있었다.
    #
    #   `\bw-\[...\]` 는 `max-w-[180px]` / `min-w-[360px]` 안의 `w-[...]` 에도 걸린다
    #   (`-` 가 비단어 문자라 그 앞에서 `\b` 가 성립한다). 앞 판본이 `max-w-[1320px]` 로
    #   한 번 당해서 `\d{3,}` 을 붙였지만 그것으로는 막히지 않는다 — 자릿수가 아니라
    #   **접두사**가 문제이기 때문이다.
    #
    #   `max-w-` 는 고정 폭이 아니라 **상한**이라 가로 넘침의 원인이 될 수 없다.
    #   `min-w-` 는 원인이 맞고, 바로 아래 줄에서 따로 센다(같은 것을 두 번 세지 않는다).
    #
    #   2026-08-20 에 스캔 범위를 `src/components` 까지 넓히자마자 이 결함이 드러났다
    #   — `SiteHeader.tsx` 의 `max-w-[180px]`(이메일 말줄임 상한)을 결함으로 보고했다.
    #   범위가 좁으면 검사기 자신의 버그도 함께 숨는다.
    CAUSES = {
        "고정 w-[NNNpx]": r"(?<!max-)(?<!min-)\bw-\[\d{3,}px\]",
        "고정 min-w-[NNNpx]": r"\bmin-w-\[\d{3,}px\]",
        "w-screen": r"\bw-screen\b",
        "100vw": r"100vw",
        "min-w-max": r"\bmin-w-max\b",
        "min-w-fit": r"\bmin-w-fit\b",
        "인라인 width:NNNpx": r"width:\s*\d{3,}px",
        "<table>": r"<table\b",
    }
    found = {k: [] for k in CAUSES}
    bare_grid = []
    for path in files:
        code = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        for name, rx in CAUSES.items():
            for m in re.finditer(rx, code):
                found[name].append("%s:%d" % (rel, code[:m.start()].count(chr(10)) + 1))
        # 3열 이상 그리드는 **반응형 접두사와 함께**여야 한다.
        #   모바일에서 3열을 강제하면 카드 하나가 100px 대로 눌린다.
        #   2열은 카드 내부 분할에 쓰이며 390px 에서도 각 170px 이라 허용한다.
        for m in re.finditer(r"[\w:-]*grid-cols-([3-9])", code):
            token = m.group(0)
            if ":" not in token:
                bare_grid.append("%s:%d %s" % (rel, code[:m.start()].count(chr(10)) + 1, token))

    for name in sorted(CAUSES):
        check("가로 넘침 원인 - %s" % name, sorted(found[name]), [])
    check("반응형 접두사 없는 3열 이상 그리드", sorted(bare_grid), [])

    # 컨테이너가 **고정 폭이 아니라 상한**인가. 화면이 각자 하드코딩하지 않는가.
    layout_ts = os.path.join(ROOT, "src", "lib", "layout.ts")
    check_true("공통 컨테이너 상수가 있다", os.path.exists(layout_ts), layout_ts)
    if os.path.exists(layout_ts):
        body = io.open(layout_ts, encoding="utf-8-sig").read()
        # ★ 토큰 경계를 정확히 본다 (2026-08-19). 처음 쓴 검사는 `\bw-\[\d` 로 찾아
        #   **`max-w-[1320px]` 안의 `w-[1` 을 잡았다** — 상한을 고정 폭으로 오인한 것이다.
        #   `-` 앞에서 `\b` 가 성립하므로 접두사가 붙은 유틸리티를 걸러내지 못한다.
        #   `max-`/`min-` 이 앞에 붙지 않은 것만 고정 폭으로 센다. 주석도 먼저 걷어낸다.
        code = _strip_comments(body)
        fixed_w = re.findall(r"(?<![-\w])w-\[\d+px\]", code)
        check_true("컨테이너는 max-w 상한을 쓴다(고정 width 아님)",
                   "max-w-" in code and not fixed_w, fixed_w or code.strip()[:120])
        check_true("모바일 좌우 패딩이 있다(px-4)", "px-4" in body, body)

    users = [os.path.relpath(p, ROOT).replace(os.sep, "/") for p in files
             if "CONTAINER" in io.open(p, encoding="utf-8-sig").read()]
    check_true("주요 화면이 공통 컨테이너를 쓴다(폭을 화면마다 새로 정하지 않는다)",
               len(users) >= 4, users)
    emit("    파일 %d개 / 컨테이너 사용 화면 %d개" % (len(files), len(users)))

def test_focus_indicator_is_never_removed_without_replacement():
    r"""포커스 표시를 지웠으면 **반드시 대체가 있어야** 한다 (2026-08-19 Sprint 221).

    ## 왜 중요한가

    키보드만 쓰는 사용자에게 포커스 링은 **마우스 커서에 해당한다.** 그것이 없으면
    "지금 어디에 있는지"를 알 수 없다. `focus:outline-none` 한 줄이 그것을 지운다.

    ## 지금 상태 (실측 2026-08-19)

    전역 리셋은 **없다.** 빌드 CSS 를 직접 확인했다 -

        .focus\:outline-none:focus                 { outline-style: none }
        .focus-visible\:outline-none:focus-visible { outline-style: none }
        :-moz-focusring                            { outline: auto }

    즉 `outline-style: none` 은 **그 유틸리티를 쓴 자리에서만** 나온다.
    나머지 요소는 브라우저 기본 `:focus-visible` 링을 그대로 갖는다.

    소스에서 그 유틸리티를 쓰는 곳은 5곳이고, **전부 대체 표시를 함께 갖고 있다**:

        login/page.tsx x2              focus:border-blue-400 (테두리 색으로 대체)
        SearchForm.tsx                 focus:ring-2 focus:ring-blue-200
        SearchPresets.tsx              focus:ring-2 focus:ring-blue-200
        SearchAccordionSection.tsx     focus-visible:ring-2 focus-visible:ring-blue-200

    이 검사는 그 규칙이 깨지지 않게 잠근다 - **지웠으면 대체가 있어야 한다.**

    ## 측정 도구가 두 번 틀렸다 (기록)

    1. 계산된 스타일로 `outline-style: none` 을 읽고 "53개 전부 포커스 표시 없음"으로
       읽었다. 그것은 **비포커스 상태의 기본값**이다(브라우저 기본 outline-style 은
       none, width 는 medium=3px). 포커스 링은 `:focus-visible` 에서만 생긴다.
    2. `el.focus()` 로 강제 포커스한 뒤 다시 쟀는데도 0 이었다 - 프로그래밍 포커스는
       Chrome 에서 `:focus-visible` 을 켜지 않는다(키보드 상호작용에서만 켜진다).

    결국 **CSS 규칙 자체**를 읽어야 답이 나왔다. 계산된 스타일은
    "지금 이 순간"만 말하고, 접근성은 **다른 순간의 규칙**에 달려 있다.
    """
    emit(chr(10) + "--- 7. 포커스 표시를 지웠으면 대체가 있는가 ---")
    files = _tsx_files() + sorted(glob.glob(os.path.join(ROOT, "src", "components", "*.tsx")))
    check_true("화면 소스를 실제로 찾았다", len(files) >= 12, len(files))

    REMOVE = re.compile(r"(?:focus|focus-visible):outline-none")
    # 대체로 인정하는 것: 링 / 테두리 색 / 그림자 / 배경 변화가 focus 상태에 걸린 것
    # ★ `outline-` 를 대체 후보에서 뺀다 (2026-08-19).
    #   처음엔 넣었는데, 그러면 `focus:outline-none` **자신이 자기 대체로 잡혀**
    #   무엇을 지워도 통과했다(변이가 그대로 통과해서 발견했다).
    #   대체는 "보이는 표시"여야 한다 - 링/테두리/그림자/배경.
    REPLACE = re.compile(r"(?:focus|focus-visible):(?:ring|border|shadow|bg)")

    offenders, used = [], []
    for path in files:
        code = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        # className 문자열 단위로 본다 - 같은 요소에 대체가 있는지가 관건이다
        for m in re.finditer(r"""(?:className=\{?[`'"]|[`'"])([^`'"]{0,600})[`'"]""", code):
            chunk = m.group(1)
            if not REMOVE.search(chunk):
                continue
            line = code[:m.start()].count(chr(10)) + 1
            used.append("%s:%d" % (rel, line))
            if not REPLACE.search(chunk):
                offenders.append("%s:%d" % (rel, line))

    # 하한 - 열거가 깨지면 0곳을 훑고 조용히 통과한다
    check_true("outline-none 을 쓰는 자리를 실제로 찾았다(검사가 공허하지 않다)",
               len(used) >= 4, used)
    check("★ 포커스 표시를 지우고 대체가 없는 자리", sorted(offenders), [])
    emit("    outline-none 사용 %d곳 / 전부 대체 있음" % len(used))

    # ★ 전제 확인: 전역으로 포커스를 지우는 리셋이 없는가.
    #   있으면 위 검사가 통과해도 **모든 요소**가 포커스 표시를 잃는다.
    css_files = sorted(glob.glob(os.path.join(ROOT, ".next", "**", "*.css"), recursive=True),
                       key=os.path.getsize, reverse=True)[:6]

    def _global_focus_resets(css):
        """전역으로 포커스 표시를 지우는 규칙만 골라낸다.

        ★ 처음 쓴 정규식은 `@supports` 블록과 주석을 선택자로 오인해
          **항상 실패**했다(변이를 넣지 않아도 울었다). at-rule 과 주석을 먼저
          걷어내고 **단순 선택자 블록**만 본다. 의도된 유틸리티
          (`.focus\\:outline-none:focus`)는 제외한다.

          이 검출기는 넣기 전에 검증했다 - 실제 CSS 0건 / 가짜 전역 리셋 주입 시 1건 /
          의도된 유틸리티 주입 시 0건.
        """
        css = re.sub(r"/\*[\s\S]*?\*/", " ", css)
        out = []
        for m in re.finditer(r"(^|[};])\s*([^@{};]{1,120}?)\s*\{([^{}]*)\}", css):
            sel, decl = m.group(2).strip(), m.group(3)
            if "outline" not in decl or "none" not in decl:
                continue
            if ":focus" in sel or "outline-none" in sel:
                continue
            out.append("%s { %s }" % (sel[:50], " ".join(decl.split())[:50]))
        return out

    global_reset, checked_css = [], 0
    for c in css_files:
        checked_css += 1
        global_reset += _global_focus_resets(
            io.open(c, encoding="utf-8", errors="replace").read())
    if checked_css == 0:
        emit("    [미확인] 빌드 CSS 가 없어 전역 리셋 여부를 확인하지 못했다"
             " (npm run build 후 재실행)")
    else:
        check("전역 포커스 리셋", sorted(set(global_reset)), [])
        emit("    빌드 CSS %d개 확인" % checked_css)


def test_semantic_landmarks_and_named_controls():
    r"""시맨틱 구조와 접근 가능한 이름 (2026-08-19 Sprint 221).

    실브라우저(`/`)로 잰 값 - main 1 / nav 1 / header 1 / h1 1 / h2 1,
    **접근 가능한 이름이 없는 대화형 요소 0개**,
    **키보드로 갈 수 없는 클릭 요소 0개**(div/span 에 onClick 만 다는 패턴이 없다).

    소스로 잠글 수 있는 것만 여기서 고정한다 - 랜드마크 요소가 사라지지 않는가,
    그리고 **아이콘만 있는 버튼에 이름이 붙어 있는가**.
    """
    emit(chr(10) + "--- 8. 시맨틱 구조 / 접근 가능한 이름 ---")
    files = _tsx_files() + sorted(glob.glob(os.path.join(ROOT, "src", "components", "*.tsx")))

    tags = {"main": 0, "nav": 0, "header": 0, "h1": 0}
    for path in files:
        code = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        for t in tags:
            tags[t] += len(re.findall(r"<" + t + r"[\s>]", code))
    for t in sorted(tags):
        check_true("<%s> 를 쓴다(랜드마크가 사라지지 않았다)" % t, tags[t] >= 1, tags[t])
    emit("    랜드마크 사용: %s" % tags)

    # 아이콘만 있는 버튼(텍스트 자식이 없는 button)에 aria-label 이 있는가.
    # 완전 정확한 JSX 파싱은 하지 않는다 - **텍스트가 전혀 없어 보이는 button** 만 본다.
    nameless = []
    for path in files:
        code = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        for m in re.finditer(r"<button\b([^>]*)>([^<]{0,40})<", code):
            attrs, inner = m.group(1), m.group(2).strip()
            if inner:
                continue
            if "aria-label" in attrs or "title=" in attrs:
                continue
            nameless.append("%s:%d" % (rel, code[:m.start()].count(chr(10)) + 1))
    check("이름 없는 아이콘 버튼", sorted(nameless), [])


def test_modals_announce_themselves():
    r"""전체 화면 모달이 **스크린리더에 모달이라고 말하는가** (2026-08-19 Sprint 221).

    상세페이지에는 전체 화면 오버레이가 둘 있다(문서 뷰어 / 사진 라이트박스).
    둘 다 `fixed inset-0 ... z-50` 로 화면 전체를 덮는다.

    실측(수정 전): `role="dialog"` 도 `aria-modal` 도 **없었다.**
    그러면 스크린리더는 "모달이 열렸다"를 알리지 못하고, **뒤의 목록·가격이 계속
    읽힌다** - 사용자는 자기가 어디에 있는지 알 수 없다.

    이것은 **픽셀을 바꾸지 않는 순수 시맨틱 결함**이라 제품 디자인 결정이 아니다.
    그래서 고쳤고, 여기서 잠근다.

    ## 이미 있던 것 (같이 고정한다)

        Escape 로 닫기 / 왼쪽·오른쪽 화살표로 사진 이동   있음
        닫기 버튼의 aria-label="닫기"                      있음
        고정 height 없음(flex-1 + min-h-0)                 큰글씨에도 깨지지 않는다

    ## 포커스 트랩 (2026-08-19 Sprint 223 정정)

    이 문서는 예전에 "포커스 트랩은 없다"고 적어 두었다. 지금은 **있다** -
    Sprint 223에서 `src/lib/useFocusTrap.ts` 로 넣었고, 그 배선은
    아래 11번 검사(`test_modals_trap_keyboard_focus`)가 잠그고 있다.
    """
    emit(chr(10) + "--- 9. 전체 화면 모달의 시맨틱 ---")
    files = _tsx_files() + sorted(glob.glob(os.path.join(ROOT, "src", "components", "*.tsx")))

    modals, missing = [], []
    for path in files:
        code = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        # 전체 화면 오버레이 = fixed inset-0 를 가진 요소. 그 여는 태그 전체를 본다.
        for m in re.finditer(r"<div[^>]*fixed inset-0[^>]*>", code):
            tag = m.group(0)
            where = "%s:%d" % (rel, code[:m.start()].count(chr(10)) + 1)
            modals.append(where)
            if "role=" not in tag or "aria-modal" not in tag:
                missing.append(where)

    # 하한 - 열거가 깨지면 0개를 훑고 조용히 통과한다
    check_true("전체 화면 모달을 실제로 찾았다(검사가 공허하지 않다)",
               len(modals) >= 2, modals)
    check("★ role/aria-modal 이 없는 전체 화면 모달", sorted(missing), [])

    # 모달에는 이름이 있어야 한다 - aria-labelledby 가 가리키는 id 가 실제로 있는가
    dangling = []
    for path in files:
        code = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        for m in re.finditer(r"aria-labelledby=[\"\']([^\"\']+)", code):
            ident = m.group(1)
            if ("id=" + chr(34) + ident + chr(34)) not in code:
                dangling.append("%s -> %s" % (rel, ident))
    check("aria-labelledby 가 없는 id 를 가리키지 않는다", sorted(dangling), [])

    # 모달 안에서 Escape 로 닫을 수 있는가 (키보드 사용자의 유일한 탈출구)
    detail = os.path.join(ROOT, "src", "app", "properties", "[id]", "page.tsx")
    body = _strip_comments(io.open(detail, encoding="utf-8-sig").read())
    check_true("모달을 Escape 로 닫는다", "Escape" in body, "키보드 탈출구가 없다")
    emit("    전체 화면 모달 %d개 / 전부 role+aria-modal 보유" % len(modals))

def _jsx_opening_tag(code, start):
    r"""`<tag` 시작 위치에서 **중괄호 깊이 0의 `>`** 까지를 여는 태그로 잘라 낸다.

    ★ 단순히 `<select[^>]*>` 로 잡으면 **`onChange={(e) => f(e)}` 의 `>` 에서 잘린다.**
      실제로 그렇게 만들었다가 "select 7개 전부 이름 없음"이라는 **거짓 결과**를 얻었다
      (브라우저로는 전부 이름이 있었다). JSX 는 속성 안에 화살표 함수가 들어가므로
      중괄호 깊이를 추적해야 한다. `=>` 의 `>` 도 태그 끝이 아니다.
    """
    depth, i = 0, start
    while i < len(code):
        ch = code[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == ">" and depth == 0:
            if i > 0 and code[i - 1] == "=":     # `=>` 는 태그 끝이 아니다
                i += 1
                continue
            return code[start:i + 1]
        i += 1
    return code[start:start + 400]


def test_form_controls_have_accessible_names():
    r"""폼 컨트롤에 **접근 가능한 이름**이 있는가 (2026-08-19 Sprint 222, BUGS #150).

    ## 무엇이 문제였나

    실브라우저(`/search`, 아코디언 전부 펼침)로 쟀다.

        폼 컨트롤 93개 중 **16개에 접근 가능한 이름이 없었다**
          select 9 / date input 2 / placeholder 만 있는 text input 5

    보이는 레이블은 `<span>` 으로 그려져 있어 **컨트롤과 프로그래밍적으로 연결돼 있지
    않다.** 스크린리더는 "콤보박스"라고만 읽고, 최소/최대가 나란히 둘이라 어느 쪽인지도
    알 수 없다. `placeholder` 는 **입력을 시작하면 사라지므로** 이름이 아니다
    (WCAG 3.3.2 Labels or Instructions).

    ## 무엇을 고쳤나

    `aria-label` 을 붙였다 — **픽셀은 하나도 바뀌지 않는다.**
    이 저장소는 이미 그 패턴을 쓰고 있었다(`시/도`, `시/군/구`, `법원` select).
    빠진 자리에 같은 방식을 적용했을 뿐이다.

        RangeSelect / PriceRangeSelect   `${label} 최소` / `${label} 최대` (공용 컴포넌트 2개 -> select 8개)
        SearchForm                       읍/면/동 · 세부주소 · 사건번호 연도/번호 · 진행상태 · 매각기일 시작/종료
        SearchPresets                    검색조건 이름
        login                            이메일 · 비밀번호

    수정 후 재측정: **93/93 이름 있음.**

    ## 이 검사가 거는 규칙

    정적으로 **감싸는 `<label>`** 을 정확히 판정하기는 어렵다(체크박스 77개가 그 패턴이다).
    그래서 **감싸는 label 로는 이름을 줄 수 없는 부류**만 본다 - 그 셋은 이 저장소에서
    전부 `aria-label` 로 이름을 준다.

        <select>              값이 여럿이라 감싸는 label 로는 어느 select 인지 알 수 없다
        <input type="date">   보이는 텍스트가 없다
        placeholder 가 있는 input   placeholder 는 이름이 아니다
    """
    emit(chr(10) + "--- 10. 폼 컨트롤의 접근 가능한 이름 ---")
    files = sorted(glob.glob(os.path.join(ROOT, "src", "**", "*.tsx"), recursive=True))
    check_true("화면 소스를 실제로 찾았다", len(files) >= 12, len(files))

    # ★ 추출기부터 검증한다 - 이 검사의 앞선 판본이 `=>` 에서 잘려 거짓 결과를 냈다.
    NL = chr(10)
    sample_ok = ("<select" + NL + "  value={x}" + NL
                 + "  onChange={(e) => f(e)}" + NL + '  aria-label="A"' + NL + ">")
    check_true("추출기 검증: 화살표 함수 뒤의 속성까지 읽는다",
               "aria-label" in _jsx_opening_tag(sample_ok, 0),
               _jsx_opening_tag(sample_ok, 0))
    sample_no = "<select" + NL + "  onChange={(e) => f(e)}" + NL + ">"
    check_true("추출기 검증: 이름이 없으면 없다고 읽는다",
               "aria-label" not in _jsx_opening_tag(sample_no, 0),
               _jsx_opening_tag(sample_no, 0))

    counts = {"select": 0, "date": 0, "placeholder": 0}
    missing = {"select": [], "date": [], "placeholder": []}
    for path in files:
        code = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        for m in re.finditer(r"<(select|input|textarea)" + chr(92) + "b", code):
            tag = _jsx_opening_tag(code, m.start())
            where = "%s:%d" % (rel, code[:m.start()].count(chr(10)) + 1)
            named = ("aria-label" in tag) or ("aria-labelledby" in tag)
            if m.group(1) == "select":
                counts["select"] += 1
                if not named:
                    missing["select"].append(where)
            if 'type="date"' in tag:
                counts["date"] += 1
                if not named:
                    missing["date"].append(where)
            if "placeholder=" in tag:
                counts["placeholder"] += 1
                if not named:
                    missing["placeholder"].append(where)

    # 하한 - 열거가 깨지면 0개를 훑고 조용히 통과한다
    check_true("폼 컨트롤을 실제로 찾았다(검사가 공허하지 않다)",
               sum(counts.values()) >= 12, counts)
    for kind in ("select", "date", "placeholder"):
        check("★ 이름 없는 %s" % kind, sorted(missing[kind]), [])
    emit("    select %d / date %d / placeholder input %d - 전부 이름 있음"
         % (counts["select"], counts["date"], counts["placeholder"]))


def test_modals_trap_keyboard_focus():
    r"""모달이 열린 동안 **키보드 포커스가 모달 안에 갇히는가** (2026-08-19 Sprint 223, BUGS #151).

    ## 실측한 결함 (수정 전, 실브라우저 `/properties/505`)

    Sprint 221이 `role="dialog"`/`aria-modal`을 붙였지만 그건 **스크린리더에게만** 하는
    말이다. 브라우저의 순차 포커스 이동은 그대로였다.

        모달을 연 직후 포커스        "대표 사진 크게 보기" - 모달 **뒤**의 버튼
        모달 안의 포커스 가능 요소    3개 / 화면 전체 24개  -> 21개가 오버레이 뒤에 살아 있다
        Tab 한 번                    "전경도 1번 크게 보기"(top 415, left 346)
                                     = 검은 오버레이에 **완전히 가려진** 버튼
        Escape 로 닫은 뒤            포커스가 헤매던 자리에 그대로 (여는 버튼으로 복귀 안 함)

    보이는 사용자에게는 아무 일도 아니지만, 키보드만 쓰는 사용자는 **자기가 어디에 있는지
    알 수 없고** 보이지 않는 버튼 위에서 Enter를 누르게 된다.

    ## 수정 후 실측 (진짜 마우스 클릭 / 진짜 Tab 키)

        사진 라이트박스 열기   포커스 -> '닫기'(모달 안)
        Tab x3                 닫기 -> 이전 사진 -> 다음 사진 -> 닫기 (순환)
        Shift+Tab              닫기 -> 다음 사진 (뒤로도 순환)
        Escape                 포커스가 **여는 버튼 바로 그 노드**로 복귀 (=== 비교로 확인)
        문서 뷰어도 동일       열기 -> '닫기', Escape -> '매각물건명세서' 버튼으로 복귀
        모달 밖으로 강제 포커스  '로그아웃'에 주자 곧바로 '닫기'로 되돌아옴

    ★ 이 검사는 소스만 본다. 위 동작은 브라우저에서만 잴 수 있고, 실측값은
      docs/SPRINT223_FOCUS_AND_STATUS_MESSAGES.md 에 남긴다.
      여기서 잠그는 것은 **배선이 끊기지 않는 것**이다 - 모달이 하나 더 생겼는데
      트랩을 안 달거나, 훅에서 복귀 코드를 지우면 여기서 걸린다.
    """
    emit(chr(10) + "--- 11. 모달 포커스 트랩 ---")

    hook = os.path.join(ROOT, "src", "lib", "useFocusTrap.ts")
    check_true("포커스 트랩 훅이 있다", os.path.exists(hook), hook)
    if not os.path.exists(hook):
        return
    src = _strip_comments(io.open(hook, encoding="utf-8-sig").read())

    # 훅이 실제로 네 가지를 다 하는가. 하나라도 빠지면 트랩이 아니다.
    check_true("열기 전 포커스를 기억한다",
               "document.activeElement" in src, "복귀할 자리를 모른다")
    check_true("Tab 을 가로챈다",
               "'Tab'" in src and "preventDefault" in src, "Tab 이 배경으로 샌다")
    # ★ "'focusin' 이 어딘가 있다"로 보면 안 된다 — 달아 두는 줄을 지워도
    #   떼내는 줄에 같은 문자열이 남아 변이가 통과했다(실제로 한 번 놓쳤다).
    check_true("Tab 이 아닌 경로로 나가는 것도 되돌린다",
               "addEventListener('focusin'" in src,
               "클릭 등으로 배경에 포커스가 가면 못 막는다")
    check_true("닫을 때 원래 자리로 되돌린다",
               "previous.focus()" in src, "닫고 나면 포커스가 미아가 된다")

    # ★ 순서가 중요하다 - 복귀 **전에** focusin 감시를 꺼야 한다.
    #   순서가 바뀌면 자기 감시기가 복귀 포커스를 다시 모달 안으로 끌고 들어온다.
    i_off = src.find("removeEventListener('focusin'")
    i_back = src.find("previous.focus()")
    check_true("focusin 감시를 복귀보다 먼저 끈다",
               i_off != -1 and i_back != -1 and i_off < i_back,
               "off=%d back=%d" % (i_off, i_back))

    # 모달마다 트랩이 실제로 **연결돼** 있는가. 훅이 있어도 안 달면 아무 일도 안 일어난다.
    files = _tsx_files() + sorted(glob.glob(os.path.join(ROOT, "src", "components", "*.tsx")))
    dialogs, untrapped = [], []
    for path in files:
        code = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        # 이 파일에서 useFocusTrap() 으로 만든 ref 이름들
        trap_refs = set(re.findall(r"const\s+(\w+)\s*=\s*useFocusTrap", code))
        for m in re.finditer(r"<div\b", code):
            tag = _jsx_opening_tag(code, m.start())
            if 'role="dialog"' not in tag:
                continue
            where = "%s:%d" % (rel, code[:m.start()].count(chr(10)) + 1)
            dialogs.append(where)
            ref = re.search(r"ref=\{(\w+)\}", tag)
            if not ref or ref.group(1) not in trap_refs:
                untrapped.append(where)

    # 하한 - 열거가 깨지면 0개를 훑고 조용히 통과한다
    check_true("모달을 실제로 찾았다(검사가 공허하지 않다)", len(dialogs) >= 2, dialogs)
    check("★ 포커스 트랩이 연결되지 않은 모달", sorted(untrapped), [])
    emit("    모달 %d개 / 전부 useFocusTrap 연결" % len(dialogs))


# 동적 상태 메시지를 **여는 태그**에 붙은 알림 역할로 판정한다.
# `errors.subscriptions ? (` 처럼 객체 속성으로 갈라지는 형태까지 잡아야 하므로
# 점 표기(`?.` 포함)를 통째로 이름으로 본다.
_STATUS_GATE = re.compile(
    r"([A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*)*)\s*(?:&&|\?)\s*\(?\s*(<[A-Za-z])")


def _status_message_sites(code):
    """`{...Error && <X ...>}` / `{errors.X ? (<Y ...>)}` 형태의 **여는 태그**를 돌려준다.

    ★ 상수 비교는 제외한다. `registryErrorCode === ERROR_CODES.REGISTRY_SUBSCRIPTION_REQUIRED ? (`
      같은 줄은 `?` 바로 앞에 **상수 이름**이 오므로 상태 메시지처럼 보이지만,
      그 분기가 그리는 것은 오류 안내가 아니라 **구독 안내 화면**이다.
      실제로 이 오탐을 한 번 냈고, 그냥 role 을 붙였으면 구독 안내 전체가
      “경고”로 읽힐 뻔했다. SCREAMING_SNAKE 조각이 들어 있으면 상수로 본다.
    """
    out = []
    for m in _STATUS_GATE.finditer(code):
        name = m.group(1)
        low = name.lower()
        if "error" not in low and "message" not in low:
            continue
        if any(re.fullmatch(r"[A-Z][A-Z0-9_]*", seg) for seg in re.split(r"\??\.", name)):
            continue
        out.append((m.start(1), name, _jsx_opening_tag(code, m.start(2))))
    return out


def test_dynamic_status_messages_are_announced():
    r"""화면에 **나중에 나타나는 안내**가 스크린리더에 전달되는가
    (2026-08-19 Sprint 223, BUGS #152).

    ## 무엇이 문제였나 (실측)

    이 서비스의 실패 안내는 전부 **비동기 결과로 나중에 나타난다** - 로그인 실패,
    관심물건 담기 실패, 검색조건 저장 실패, 목록 로드 실패. 그런데 나타날 때
    **아무것도 읽히지 않았다.** 실브라우저 `/search` 로 잰 값:

        aria-live / role=alert / role=status 를 가진 요소   **0개**

    보는 사람은 빨간 글씨가 생긴 걸 보지만, 듣는 사람에게는 아무 일도 일어나지 않은
    것과 구별되지 않는다. 특히 로그인은 **제출해도 아무 반응이 없는 화면**이 된다
    (WCAG 4.1.3 Status Messages, AA).

    `role="alert"` / `role="status"` 는 **픽셀을 하나도 바꾸지 않는다** - 색·크기·간격
    같은 제품 결정이 아니라서 그대로 고쳤다.

    ## 이 검사가 거는 규칙

    "값이 있을 때만 나타나는 JSX" 중 그 조건 이름에 `error`/`message` 가 들어간 것은
    **나타나는 그 요소 자체**가 알림 역할을 가져야 한다. 안쪽 자식에 붙이면
    바깥 요소가 나타나는 순간을 놓칠 수 있어서, 조건이 감싸는 **여는 태그**에 요구한다.
    """
    emit(chr(10) + "--- 12. 동적 상태 메시지의 알림 ---")
    files = _tsx_files() + sorted(glob.glob(os.path.join(ROOT, "src", "components", "*.tsx")))

    # ★ 탐지기부터 검증한다 - 이 파일은 앞서 `<select[^>]*>` 가 `=>` 에서 잘려
    #   거짓 결과를 낸 전례가 있다.
    NL = chr(10)
    probe_ok = "{favError && (" + NL + '  <div role="alert" className="x">' + NL + "    {favError}"
    probe_no = "{favError && (" + NL + '  <div className="x">' + NL + "    {favError}"
    probe_skip = "{r.status === 'F' && r.reason && (" + NL + '  <p className="x">'
    check_true("탐지기 검증: 알림이 있으면 있다고 읽는다",
               len(_status_message_sites(probe_ok)) == 1
               and "alert" in _status_message_sites(probe_ok)[0][2],
               _status_message_sites(probe_ok))
    check_true("탐지기 검증: 알림이 없으면 없다고 읽는다",
               len(_status_message_sites(probe_no)) == 1
               and "alert" not in _status_message_sites(probe_no)[0][2],
               _status_message_sites(probe_no))
    check_true("탐지기 검증: error/message 가 아닌 조건은 세지 않는다",
               _status_message_sites(probe_skip) == [], _status_message_sites(probe_skip))

    sites, silent, by_live_region = [], [], []
    for path in files:
        code = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        # ★ 이미 **항상 존재하는 live region** 으로 상태를 알리는 화면은 건너뚴다.
        #   거기에 개별 메시지까지 role 을 달면 **두 번 읽힌다** — 검색 화면이 그렇다.
        #   (그 한 줄이 실제로 있는지는 아래에서 따로 단언한다.)
        if re.search(r'className="sr-only"[^>]*role="status"', code):
            by_live_region.append(rel)
            continue
        for pos, name, tag in _status_message_sites(code):
            where = "%s:%d(%s)" % (rel, code[:pos].count(NL) + 1, name)
            sites.append(where)
            if not re.search(r'role="(alert|status)"|aria-live=', tag):
                silent.append(where)

    # 하한 - 열거가 깨지면 0곳을 훑고 조용히 통과한다
    check_true("동적 상태 메시지를 실제로 찾았다(검사가 공허하지 않다)",
               len(sites) >= 10, sites)
    check("★ 나타나도 읽히지 않는 상태 메시지", sorted(silent), [])
    emit("    동적 상태 메시지 %d곳 / 전부 alert|status" % len(sites))
    if by_live_region:
        emit("    항상 존재하는 live region 으로 알리는 화면(중복 알림 방지): %s"
             % ", ".join(sorted(by_live_region)))

    # 오류 안내가 **그 컨트롤과 연결**돼 있는가 (aria-describedby).
    # role="alert" 는 나타나는 순간만 읽힌다 — 나중에 Tab 으로 그 컨트롤에
    # 도착한 사람은 이유를 모른다. 그리고 가리키는 id 가 실제로 있어야 한다 —
    # 없는 번지를 가리키는 aria-describedby 는 **아무 것도 읽어 주지 않고** 조용히 사라진다.
    dangling, described = [], 0
    for path in files:
        code = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        ids = set(re.findall(r"id=[\"']([^\"']+)[\"']", code))
        for m in re.finditer(r"aria-(?:describedby|labelledby)=(\{[^}]*\}|[\"'][^\"']+[\"'])", code):
            raw = m.group(1)
            for ident in re.findall(r"[\"']([\w-]+)[\"']", raw):
                described += 1
                if ident not in ids:
                    dangling.append("%s -> %s" % (rel, ident))
    check_true("aria-describedby/labelledby 를 실제로 찾았다", described >= 3, described)
    check("★ 없는 id 를 가리키는 aria-describedby/labelledby", sorted(dangling), [])

    # 필드 옆에 붙는 오류는 그 필드와 연결돼 있어야 한다.
    form_src = _strip_comments(io.open(
        os.path.join(ROOT, "src", "app", "search", "SearchForm.tsx"),
        encoding="utf-8-sig").read())
    check_true("시/군/구 오류가 그 select 와 연결돼 있다",
               "aria-describedby={sigunguError" in form_src
               and 'id="sigungu-error"' in form_src,
               "오류를 놓친 뒤 Tab 으로 오면 이유를 알 수 없다")

    # 검색 결과 자체는 **항상 존재하는 한 줄**로 알린다.
    # 결과 목록에 aria-live 를 달면 0건일 때 그 문단이 통째로 사라져 아무것도 못 알린다.
    screen = os.path.join(ROOT, "src", "app", "search", "SearchScreen.tsx")
    body = _strip_comments(io.open(screen, encoding="utf-8-sig").read())
    live = re.search(r'<p className="sr-only"[^>]*role="status"[^>]*aria-live="polite"', body)
    check_true("검색 화면에 항상 존재하는 상태 한 줄이 있다", bool(live),
               "검색 결과가 바뀌어도 아무것도 읽히지 않는다")
    if live:
        # 조건부로 렌더되면 "항상 존재"가 깨진다 - 바로 앞이 조건 연산자로 끝나면 안 된다.
        head = body[:live.start()].rstrip()
        check_true("그 한 줄이 조건부로 렌더되지 않는다",
                   not head.endswith("&&") and not head.endswith("?"),
                   head[-40:])


def test_every_screen_has_a_main_landmark():
    r"""**화면마다** `<main>` 랜드마크가 있는가 (2026-08-19 Sprint 223, BUGS #153).

    ## 이 결함은 기존 가드의 맹점에서 나왔다

    8번 검사는 `<main>` 사용 횟수를 **저장소 전체로 합산**해서 `>= 1` 인지만 봤다.
    검색 화면 하나가 갖고 있으면 나머지 화면이 전부 없어도 통과한다 —
    실제로 그랬다. 실브라우저로 화면별로 재 보고서야 드러났다.

        /search        main 1
        /properties/{id}   main **0**   <- 상세페이지에 본문 랜드마크가 없다
        /favorites         main **0**
        /properties/recent main **0**
        /login             main **0**
        /mypage        main 1

    `<main>` 이 없으면 스크린리더 사용자는 **헤더/내비를 건너뛰고 본문으로 갈 수단이
    없다**(WCAG 2.4.1 Bypass Blocks). 상세페이지는 이 서비스에서 가장 오래 머무는
    화면인데 매번 상단 메뉴부터 다시 들어야 했다.

    ## 무엇을 고쳤나

    감싸는 `<div>` 의 **태그만** `<main>` 으로 바꿨다 — className 은 그대로라
    **픽셀은 하나도 바뀌지 않는다**(실측: 상세 grid 622px+622px / 컨테이너 1320px /
    가로 오버플로 0, 로그인 flex·min-height 911px 그대로).
    로딩·실패 분기에도 같은 방식으로 넣어, 어느 상태에서도 랜드마크가 있다.

    ## 이 검사가 거는 규칙

    "화면"은 `src/app/**/page.tsx` 와 `*Screen.tsx` 다. 단 **JSX 를 그리지 않는
    라우트**(예: `/properties` 는 `redirect('/')` 한 줄)는 화면이 아니므로 제외한다.
    """
    emit(chr(10) + "--- 13. 화면마다 main 랜드마크 ---")

    screens = sorted(
        glob.glob(os.path.join(ROOT, "src", "app", "**", "page.tsx"), recursive=True)
        + glob.glob(os.path.join(ROOT, "src", "app", "**", "*Screen.tsx"), recursive=True))

    checked, missing, redirects, branch_gap = [], [], [], []
    for path in screens:
        code = _strip_comments(io.open(path, encoding="utf-8-sig").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        # JSX 를 아예 그리지 않는 라우트는 화면이 아니다.
        if not re.search(r"<[A-Za-z][^>]*>", code):
            redirects.append(rel)
            continue
        # 다른 컴포넌트에 화면 전체를 위임하는 얇은 page.tsx 는 그 컴포넌트가 책임진다.
        # (`/` 와 `/search` 가 둘 다 SearchScreen 을 그린다.)
        if re.search(r"<\w*Screen\b", code):
            redirects.append(rel + " (Screen 위임)")
            continue
        checked.append(rel)
        if "<main" not in code:
            missing.append(rel)
            continue
        # ★ 파일에 하나만 있으면 된다고 보면 **분기 하나가 랜드마크를 잃어도** 모른다.
        #   이 화면들은 로딩 / 실패 / 본문 분기를 각각 `min-h-screen` 으로 시작하므로
        #   그 개수만큼 main 이 있어야 한다. 변이로 확인했다 — 상세의 본문 main 하나를
        #   div 로 되돌리면 **파일 단위 검사는 못 잡았고** 이 줄이 잡는다.
        #   매음: 화면 루트를 `min-h-screen` 이 아닌 방식으로 쓰면 이 비교는 무력해진다
        #   — 지금 저장소의 6개 화면은 전부 그 규칙을 따른다.
        roots = len(re.findall(r"min-h-screen", code))
        mains = len(re.findall(r"<main" + chr(92) + "b", code))
        if roots and mains < roots:
            branch_gap.append("%s (화면 루트 %d / main %d)" % (rel, roots, mains))

    # 하한 - 열거가 깨지면 0개를 훑고 조용히 통과한다
    check_true("화면을 실제로 찾았다(검사가 공허하지 않다)", len(checked) >= 5, checked)
    check("★ main 랜드마크가 없는 화면", sorted(missing), [])
    check("★ 분기 중 일부가 main 을 잃은 화면", sorted(branch_gap), [])
    emit("    화면 %d개 전부 main 보유 / 위임·리다이렉트 %d개 제외: %s"
         % (len(checked), len(redirects), ", ".join(redirects)))


def test_measured_baseline_is_recorded():
    """실측 결과가 **문서에 남아 있는가.**

    이 파일이 잠그는 것은 소스의 사용 횟수뿐이다. 실제 대비/탭타깃 수치는
    실브라우저로만 잴 수 있고, 재지 않으면 다음 사람은 "몇이었는지"를 모른다.
    그래서 그 수치가 문서에 적혀 있는지까지 확인한다 —
    **문서가 사라지면 이 검사가 먼저 운다.**
    """
    emit("\n--- 4. 실측 수치가 문서에 남아 있는가 ---")
    doc = os.path.join(ROOT, "docs", "SPRINT219_ACCESSIBILITY_AUDIT.md")
    check_true("Sprint 문서가 있다", os.path.exists(doc), doc)
    if not os.path.exists(doc):
        return
    body = io.open(doc, encoding="utf-8-sig").read()
    # ★ 2026-08-20 Sprint 225: "WCAG 2.5.8 위반" 이라는 서술이 **틀렸다**는 정정이
    #   문서에 남아 있는지도 함께 본다. 정정이 사라지면 다음 사람이 같은 오판을 반복한다.
    for token in ("2.6:1", "4.5:1", "WCAG 2.5.8", "oklch", "11px",
                  "간격(Spacing) 예외"):
        check_true("문서에 %s 가 적혀 있다" % token, token in body,
                   "실측 근거가 사라지면 수치의 뜻을 알 수 없다")


if __name__ == "__main__":
    test_small_and_low_contrast_text_does_not_grow()
    test_zoom_is_not_disabled()
    test_list_and_detail_keep_semantic_alt_rules()
    test_no_structural_mobile_overflow()
    test_root_font_scaling_reaches_the_text()
    test_focus_indicator_is_never_removed_without_replacement()
    test_semantic_landmarks_and_named_controls()
    test_modals_announce_themselves()
    test_form_controls_have_accessible_names()
    test_modals_trap_keyboard_focus()
    test_dynamic_status_messages_are_announced()
    test_every_screen_has_a_main_landmark()
    test_measured_baseline_is_recorded()

    emit("\n" + "=" * 55)
    if failures:
        emit("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    emit("ALL FRONTEND ACCESSIBILITY TESTS PASSED")
