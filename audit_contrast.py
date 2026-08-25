# -*- coding: utf-8 -*-
"""화면에 **실제로 그려진** 글자의 명암비를 잰다 (WCAG 1.4.3) - 2026-08-21 Sprint 247 신설.

실행:  python audit_contrast.py            (Next dev 서버가 떠 있어야 한다)
       읽기 전용이다. 아무것도 바꾸지 않는다.

## 왜 필요한가 - 기존 검사는 **문자열을 세고 있었다**

`test_frontend_accessibility.py` 는 1,143줄이지만 `text-gray-400` 이 소스에 몇 번
나오는지를 세고 상한을 걸어 둔다(현재 110개). 그건 **개수**지 명암비가 아니다:

  - 그 클래스가 실제로 어떤 배경 위에 놓이는지 모른다 (흰 배경이냐 회색 카드냐)
  - 큰 글씨는 기준이 다르다 (WCAG: 24px+ 또는 18.66px+bold 는 3:1)
  - 클래스가 아니라 상속/inline 으로 정해진 색은 아예 세지 않는다
  - 흰 글자를 파란 버튼에 올린 경우처럼 **배경이 핵심인** 조합을 볼 수 없다

같은 세션에 큰 글씨(200%)를 처음 렌더링해서 재 봤더니 결함 2건이 나왔다.
대비도 같은 이유로 실제로 잰다.

## 방법

텍스트 노드마다 계산된 `color` 와, 위로 올라가며 만나는 배경들을 알파합성해
WCAG 상대휘도 공식으로 명암비를 낸다. 상속 `opacity` 도 곱해서 반영한다.

### ★ 색 문자열을 직접 파싱하지 않는다

Tailwind v4 의 계산값은 `lab(...)` / `oklch(...)` 로 나온다. `rgb()` 정규식만 쓰면
전부 파싱 실패 -> 배경이 흰색으로 떨어져 **파란 버튼 위 흰 글자가 1.00:1 로 오탐**된다
(2026-08-21 에 실제로 12건 오탐하고 잡았다). 그래서 캔버스에 **실제로 칠해서**
sRGB 바이트를 읽는다 - 색 공간과 무관하게 브라우저가 그리는 값이 나온다.

### ★ 도구를 먼저 검증한다

두 가지를 매번 확인하고, 어느 하나라도 어긋나면 **결과를 쓰지 않고 종료한다**:

  1. 판정 로직   흰 배경 위 검정(21:1) 통과 / 흰 글자(1:1) 결함 / #767676(4.54:1) 통과
  2. 색공간      lab()/oklch()/hex/알파가 sRGB 로 제대로 해석되는가

처음엔 2번을 "파랑 위 흰 글자는 통과해야 한다"로 검증하려 했는데, **그 전제가 틀렸다** -
Tailwind blue-500 위 흰 글자는 실제로 3.68:1 이라 AA 미달이다. 도구가 아니라 내 기대가
틀렸던 것이라, 판정 결과가 아니라 **파서 반환값**을 직접 보도록 바꿨다.
"""
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.environ.get("REPO", os.getcwd()))
import audit_viewport as AV  # noqa: E402

BASE = os.environ.get("VIEWPORT_BASE", "http://localhost:3000")
SCREENS = [("/", 200), ("/search?sido=%EC%84%9C%EC%9A%B8", 200), ("/login", 20)]
WIDTH = 390

CONTRAST_JS = r"""
// ★ 색 문자열을 직접 파싱하지 않는다. **캔버스에 실제로 칠해서** sRGB 바이트를 읽는다.
//   Tailwind v4 의 계산값은 `lab(...)` / `oklch(...)` 로 나온다 - rgb() 정규식만 쓰면
//   전부 null 이 되어 배경이 흰색으로 떨어지고, 파란 버튼 위 흰 글자가 1.00:1 로
//   **오탐**된다(2026-08-21 실제로 12건 오탐하고 잡았다). 캔버스는 색 공간과 무관하게
//   브라우저가 실제로 그리는 값을 준다.
var _cv = document.createElement('canvas'); _cv.width = _cv.height = 1;
var _cx = _cv.getContext('2d', {willReadFrequently:true});
var _memo = {};
function parse(c){
  if (c == null || c === '') return null;
  if (_memo[c] !== undefined) return _memo[c];
  _cx.clearRect(0,0,1,1);
  try { _cx.fillStyle = '#000'; _cx.fillStyle = c; } catch(e){ _memo[c] = null; return null; }
  _cx.fillRect(0,0,1,1);
  var d = _cx.getImageData(0,0,1,1).data;
  var v = [d[0], d[1], d[2], d[3]/255];
  _memo[c] = v;
  return v;
}
function over(fg, bg){                       // fg 를 bg 위에 알파합성
  var a = fg[3];
  return [ fg[0]*a + bg[0]*(1-a), fg[1]*a + bg[1]*(1-a), fg[2]*a + bg[2]*(1-a), 1 ];
}
function lum(c){
  var s = [c[0],c[1],c[2]].map(function(v){
    v /= 255;
    return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4);
  });
  return 0.2126*s[0] + 0.7152*s[1] + 0.0722*s[2];
}
function ratio(a, b){
  var l1 = lum(a), l2 = lum(b);
  if (l1 < l2){ var t = l1; l1 = l2; l2 = t; }
  return (l1 + 0.05) / (l2 + 0.05);
}
function bgOf(el){
  var cur = el, acc = [255,255,255,1];         // 페이지 바탕은 흰색으로 본다
  var stack = [];
  while (cur && cur.nodeType === 1){
    var cs = getComputedStyle(cur);
    var c = parse(cs.backgroundColor);
    if (c && c[3] > 0) stack.push(c);
    if (c && c[3] === 1) break;                // 불투명 배경을 만나면 멈춘다
    cur = cur.parentElement;
  }
  for (var i = stack.length - 1; i >= 0; i--) acc = over(stack[i], acc);
  return acc;
}
function effOpacity(el){
  var o = 1, cur = el;
  while (cur && cur.nodeType === 1){
    var v = parseFloat(getComputedStyle(cur).opacity);
    if (!isNaN(v)) o *= v;
    cur = cur.parentElement;
  }
  return o;
}

var out = [], seen = 0;
var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
var node;
while ((node = walker.nextNode())){
  var txt = (node.nodeValue || '').trim();
  if (!txt) continue;
  var el = node.parentElement;
  if (!el) continue;
  var cs = getComputedStyle(el);
  if (cs.visibility === 'hidden' || cs.display === 'none') continue;
  var r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) continue;
  if (el.closest('[aria-hidden="true"]')) continue;
  // sr-only 등 화면에서 안 보이는 것은 제외
  if (r.width <= 2 && r.height <= 2) continue;
  seen++;

  var fg = parse(cs.color); if (!fg) continue;
  var bg = bgOf(el);
  var op = effOpacity(el);
  fg = [fg[0], fg[1], fg[2], fg[3] * op];
  var fgc = over(fg, bg);
  var cr = ratio(fgc, bg);

  var size = parseFloat(cs.fontSize);
  var weight = parseInt(cs.fontWeight, 10) || 400;
  var large = (size >= 24) || (size >= 18.66 && weight >= 700);
  var need = large ? 3.0 : 4.5;

  if (cr + 0.05 < need){
    out.push({
      text: txt.slice(0, 34),
      tag: el.tagName, cls: (el.className || '').toString().slice(0, 52),
      color: cs.color, bg: 'rgb(' + Math.round(bg[0]) + ',' + Math.round(bg[1]) + ',' + Math.round(bg[2]) + ')',
      size: size, weight: weight, large: large,
      ratio: Math.round(cr * 100) / 100, need: need
    });
  }
}
return { seen: seen, bad: out, probe: {
     'lab':   parse('lab(54.1736 13.3368 -74.6839)'),
     'oklch': parse('oklch(0.623 0.214 259.815)'),
     'hex':   parse('#767676'),
     'rgba0': parse('rgba(0, 0, 0, 0)'),
     'white_on_blue500': (function(){
        var b = parse('#3b82f6'), w = parse('#ffffff');
        return Math.round(ratio(w, b) * 100) / 100;
     })()
   } };
"""

SELFTEST_JS = r"""
var d = document.createElement('div');
d.style.cssText = 'position:fixed;left:0;top:0;background:#ffffff;padding:4px;z-index:99999';
d.innerHTML = '<span style="color:#000">가</span>' +
              '<span style="color:#fff">나</span>' +
              '<span style="color:#767676">다</span>';
document.body.appendChild(d);
return true;
"""


def console_safe(text, enc=None):
    """콘솔 인코딩으로 못 내보내는 글자를 대체 문자로 바꾼다 (2026-08-25, BUGS #193).

    ## 왜 필요한가 - 실제로 리포트가 중간에서 끊겼다

    2026-08-25 이 도구를 dev 서버에 대고 처음 끝까지 돌렸더니, 기준 미달 43곳을
    **다 찾아 놓고** 목록을 찍다가 죽었다:

        UnicodeEncodeError: 'cp949' codec can't encode character '—'

    화면에서 긁어 온 문구에 엠대시가 있었기 때문이다. 즉 **측정은 성공했는데
    보고가 실패**했고, 종료코드도 1(결함 있음)이 아니라 트레이스백이 됐다.

    이 저장소의 `test_console_encoding.py` 는 **소스에 박힌 문자열**을 검사한다.
    그런데 여기서 터진 것은 소스가 아니라 **측정 대상 데이터**다 - 화면 문구에는
    어떤 글자든 올 수 있으므로 검사로 막을 수 없고, 찍는 쪽에서 처리해야 한다.

    stdout 을 통째로 재설정하지 않는 이유: 이 도구는 다른 도구가 import 하기도 하고
    (`audit_contrast` -> `audit_viewport`), 전역 스트림을 바꾸면 호출부의 인코딩까지
    바뀐다. 바꾸는 범위를 **찍는 문자열 하나**로 좁힌다.
    """
    enc = enc or getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return text.encode(enc, "replace").decode(enc, "replace")
    except (LookupError, UnicodeError):
        return text


def _encodable(text, enc):
    try:
        text.encode(enc)
        return True
    except Exception:
        return False


def contrast_verdict(per_screen, all_bad):
    """(종료코드, 사유). 0=기준 미달 없음 / 1=결함 있음 / 2=재지 못했다.

    ## 왜 이 함수가 따로 있는가 (2026-08-25, docs/BUGS.md #193)

    예전에는 main() 끝이 이랬다.

        if not all_bad:
            return 0

    `all_bad` 가 비는 경우는 **둘**인데 코드는 하나로 봤다:

        (a) 진짜로 기준 미달이 없다                  -> 0 이 맞다
        (b) 화면이 안 그려져 **잰 글자가 없다**       -> 0 은 거짓이다

    (b) 는 서버가 죽었거나, 라우트가 바뀌었거나, 렌더가 20초 안에 안 끝났을 때 나온다.
    그때 이 도구는 "합계: 텍스트 노드 0개 / 기준 미달 0개" 를 찍고 **종료코드 0** 을
    돌려준다 - 즉 아무것도 재지 않고 "정상"이라고 말한다. 이 저장소가 반복해서 당한
    거짓 통과 그 자체다(`audit_viewport.py` 는 같은 함정을 `nodes < 15 -> UNUSABLE`
    로 이미 막고 있었다. 이 도구만 빠져 있었다).

    ## 하한을 왜 "0 개" 로만 두는가

    화면별 텍스트 노드 수의 **정상 범위를 아직 재지 않았다**(dev 서버가 떠 있어야
    잴 수 있다). 재지 않은 값을 상수로 박으면 그것이 다음 오판의 근거가 된다.
    그래서 지금은 부정할 수 없는 것만 판정한다 - **그려진 화면에 텍스트 노드가
    0 개일 수는 없다.** 실측 기준선이 생기면 그때 하한을 올린다.
    """
    empty = [path for path, seen in per_screen if seen <= 0]
    if not per_screen:
        return 2, "측정한 화면이 하나도 없다"
    if empty:
        return 2, ("텍스트 노드를 하나도 못 본 화면이 있다: %s"
                   " - 화면이 그려지지 않았다는 뜻이라 '기준 미달 0'은 근거가 없다"
                   % ", ".join(empty))
    if all_bad:
        return 1, "기준 미달 %d곳" % len(all_bad)
    return 0, "기준 미달 없음"


def selftest() -> int:
    """브라우저도 서버도 네트워크도 쓰지 않고 판정 로직을 검증한다.

    이 도구에는 원래 `--selftest` 가 없었다(BUGS #188 이 "남은 것"으로 적어 둔 항목).
    실제 명암비 계산은 브라우저 안 JS 라 회귀 스위트에 넣을 수 없지만,
    **종료코드 계약**은 여기서 전부 잠근다.
    """
    fails = []

    def check(name, cond, detail=""):
        print("[%s] %s%s" % ("PASS" if cond else "FAIL", name,
                             "" if cond else " -- %s" % (detail,)))
        if not cond:
            fails.append(name)

    print("--- contrast_verdict(): 재지 못한 것을 정상으로 뭉개지 않는가 ---")
    full = [("/", 400), ("/search", 350), ("/login", 40)]

    code, why = contrast_verdict(full, [])
    check("전부 재고 기준 미달이 없으면 0", code == 0, (code, why))

    code, why = contrast_verdict(full, [{"text": "x"}])
    check("기준 미달이 있으면 1", code == 1, (code, why))

    # ★ 이 도구의 원래 결함이 정확히 이 자리였다.
    code, why = contrast_verdict([("/", 0), ("/search", 350), ("/login", 40)], [])
    check("한 화면이라도 0 개면 2(측정 불가)", code == 2, (code, why))
    check("어느 화면이 비었는지 이름을 남긴다", "/" in why, why)

    code, why = contrast_verdict([("/", 0), ("/search", 0), ("/login", 0)], [])
    check("전 화면이 0 개면 2", code == 2, (code, why))

    code, why = contrast_verdict([], [])
    check("잰 화면이 없으면 2", code == 2, (code, why))

    # 빈 화면이면 **기준 미달이 있어도** 결과를 믿을 수 없다 -> 1 이 아니라 2 다.
    code, why = contrast_verdict([("/", 0)], [{"text": "x"}])
    check("못 잰 화면이 있으면 결함 목록이 있어도 2", code == 2, (code, why))

    check("자기 검증: 세 종류 판정이 실제로 갈린다",
          len({contrast_verdict(full, [])[0],
               contrast_verdict(full, [{"t": 1}])[0],
               contrast_verdict([("/", 0)], [])[0]}) == 3)

    print("--- console_safe(): 화면 문구가 콘솔 인코딩을 넘어도 죽지 않는다 ---")
    # 실제로 여기서 죽었다 - cp949 콘솔 + 엠대시(U+2014). 측정은 다 해 놓고
    # 보고를 못 해서 트레이스백이 됐다(BUGS #193).
    hard = "— ★ 안녕 😀"
    out = console_safe(hard)
    check("반환값은 문자열이다", isinstance(out, str), type(out))
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        out.encode(enc)
        encodable = True
    except Exception as exc:
        encodable = exc
    check("현재 콘솔 인코딩(%s)으로 내보낼 수 있다" % enc, encodable is True, encodable)
    # ★ 주변 환경(PYTHONIOENCODING)에 흔들리지 않게 인코딩을 **명시해서** 잰다.
    #   회귀 스위트는 utf-8 로 돌리므로, stdout 에만 기대면 이 검사가 공허해진다.
    cp = console_safe(hard, enc="cp949")
    check("cp949 를 지정하면 cp949 로 내보낼 수 있다", _encodable(cp, "cp949"), cp)
    check("cp949 에 없는 글자는 남지 않는다",
          "—" not in cp and "😀" not in cp, cp)
    check("utf-8 을 지정하면 원문 그대로", console_safe(hard, enc="utf-8") == hard,
          console_safe(hard, enc="utf-8"))
    check("ASCII 는 그대로 둔다", console_safe("plain-ascii") == "plain-ascii",
          console_safe("plain-ascii"))

    print("--- build_driver(): 이 도구도 트레이스백 대신 판정을 낸다 ---")
    err = None
    try:
        AV.build_driver(False, 390, 900, factories=[
            ("A", lambda h, w, ht: (_ for _ in ()).throw(RuntimeError("SSL 실패")))])
    except AV.DriverUnavailable as exc:
        err = str(exc)
    except Exception as exc:
        err = "WRONG:%s" % type(exc).__name__
    check("드라이버 실패는 DriverUnavailable 이다",
          err is not None and not err.startswith("WRONG:"), err)
    check("사유가 남는다", err is not None and "SSL 실패" in err, err)

    print()
    if fails:
        print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
        return 1
    print("ALL SELFTESTS PASSED (audit_contrast.py)")
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()

    print("=" * 92)
    print(" 렌더링된 글자의 명암비 (WCAG 1.4.3) - %dpx" % WIDTH)
    print("=" * 92)

    # 서버부터 확인한다 - 없는데 "기준 미달 0" 이라고 말하지 않기 위해서다
    # (`audit_viewport.py` 는 이미 이렇게 한다. 이 도구만 빠져 있었다).
    import urllib.request
    try:
        urllib.request.urlopen(BASE, timeout=8).read(1)
    except Exception as e:
        print("WEB 서버(%s)에 연결할 수 없다: %s: %s"
              % (BASE, type(e).__name__, str(e)[:160]))
        print("먼저 `npm run dev` 로 띄운 뒤 다시 실행하라. (측정 불가 = 종료코드 2)")
        return 2

    try:
        drv = AV.build_driver(headed=False, width=WIDTH, height=1000)
    except AV.DriverUnavailable as e:
        # 예전에는 여기서 40줄짜리 트레이스백이 그대로 나왔다(BUGS #193).
        print("브라우저를 띄우지 못했다 - 시도한 방법과 사유:")
        for reason in str(e).split("; "):
            print("    %s" % reason)
        print("(측정 불가 = 종료코드 2. 정상으로 뭉개지 않는다.)")
        return 2
    except Exception as e:
        print("브라우저를 띄우지 못했다: %s: %s" % (type(e).__name__, str(e)[:200]))
        print("(측정 불가 = 종료코드 2. 정상으로 뭉개지 않는다.)")
        return 2
    total_seen = 0
    all_bad = []
    per_screen = []      # (경로, 잰 텍스트 노드 수) - 재지 못한 화면을 구분하기 위해 (#193)
    try:
        AV.set_viewport(drv, WIDTH, 1000)

        # ---- 도구 검증 -------------------------------------------------
        drv.get(BASE + "/login")
        time.sleep(1.5)
        drv.execute_script(SELFTEST_JS)
        time.sleep(0.3)
        probe = drv.execute_script(CONTRAST_JS)
        names = {b["text"] for b in probe["bad"]}
        print("  [도구 검증-1] 흰 배경 위 검정/흰색/#767676 로 판정 로직 확인")
        print("     흰 글자('나')를 결함으로 잡았는가 : %s" % ("예" if "나" in names else "아니오 <- 도구 이상"))
        print("     검정('가')을 오탐하지 않았는가     : %s" % ("예" if "가" not in names else "아니오 <- 도구 이상"))
        print("     경계값 #767676('다') 통과시켰는가  : %s" % ("예" if "다" not in names else "아니오 <- 도구 이상"))

        # ★ 색공간 눈멂은 **판정 결과가 아니라 파서 반환값**으로 본다.
        #   처음엔 "파랑 위 흰 글자는 통과해야 한다"로 검증하려 했는데, 그 전제 자체가
        #   틀렸다 - Tailwind blue-500 위 흰 글자는 실제로 3.68:1 이라 AA 미달이다.
        #   도구가 아니라 내 기대가 틀렸던 것이다(2026-08-21).
        pr = probe.get("probe", {})
        print("  [도구 검증-2] 색 문자열이 색공간과 무관하게 sRGB 로 해석되는가")
        print("     lab(...)   -> %s" % (pr.get("lab"),))
        print("     oklch(...) -> %s" % (pr.get("oklch"),))
        print("     #767676    -> %s" % (pr.get("hex"),))
        print("     rgba(0,0,0,0) -> %s (알파 0 이어야 한다)" % (pr.get("rgba0"),))
        print("     참고: 흰 글자 on #3b82f6(blue-500) = %s:1" % (pr.get("white_on_blue500"),))
        blind = (not pr.get("lab")) or (not pr.get("oklch")) or (pr.get("hex") or [0])[0] != 118
        if blind:
            print("  ★ 색공간을 해석하지 못한다. 결과를 쓰지 않는다.")
            return 2
        if "나" not in names or "가" in names:
            print("  ★ 판정 로직이 신뢰할 수 없다. 결과를 쓰지 않는다.")
            return 2
        print()

        # ---- 본 측정 ---------------------------------------------------
        for path, minn in SCREENS:
            drv.get(BASE + path)
            dl = time.time() + 20
            while time.time() < dl:
                try:
                    if drv.execute_script(
                            "return document.body?document.body.querySelectorAll('*').length:0") >= minn:
                        break
                except Exception:
                    pass
                time.sleep(0.3)
            time.sleep(1.2)
            r = drv.execute_script(CONTRAST_JS)
            total_seen += r["seen"]
            per_screen.append((path.split("?")[0], r["seen"]))
            for b in r["bad"]:
                b["path"] = path.split("?")[0]
            all_bad.extend(r["bad"])
            print("  %-10s 텍스트 노드 %4d개 검사 / 기준 미달 %d개"
                  % (path.split("?")[0], r["seen"], len(r["bad"])))
    finally:
        try:
            drv.quit()
        except Exception:
            pass

    print()
    print("  합계: 텍스트 노드 %d개 / 기준 미달 %d개" % (total_seen, len(all_bad)))

    code, why = contrast_verdict(per_screen, all_bad)
    if code == 2:
        print("  ★ 측정 불가: %s" % why)
        print("     화면별: %s"
              % ", ".join("%s=%d" % (pth, n) for pth, n in per_screen))
        print("     (종료코드 2. 재지 못한 것을 \"기준 미달 0\" 으로 돌려주지 않는다 - docs/BUGS.md #193)")
        return 2
    if code == 0:
        return 0

    print()
    print("  기준 미달 상세 (같은 색+크기끼리 묶음)")
    print("  " + "-" * 88)
    g = defaultdict(list)
    for b in all_bad:
        g[(b["color"], b["bg"], b["size"], b["need"], b["ratio"])].append(b)
    for (color, bg, size, need, ratio), items in sorted(g.items(), key=lambda kv: kv[0][4]):
        print(console_safe("    %s on %s  %gpx  실측 %.2f:1  (기준 %.1f:1)  %d곳"
                           % (color, bg, size, ratio, need, len(items))))
        for b in items[:3]:
            print(console_safe("        %-9s %-26s %s"
                               % (b["path"], repr(b["text"])[:26], b["cls"][:44])))
    return 1


if __name__ == "__main__":
    sys.exit(main())
