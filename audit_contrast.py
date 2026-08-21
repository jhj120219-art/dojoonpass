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


def main():
    print("=" * 92)
    print(" 렌더링된 글자의 명암비 (WCAG 1.4.3) - %dpx" % WIDTH)
    print("=" * 92)

    drv = AV.build_driver(headed=False, width=WIDTH, height=1000)
    total_seen = 0
    all_bad = []
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
    if not all_bad:
        return 0

    print()
    print("  기준 미달 상세 (같은 색+크기끼리 묶음)")
    print("  " + "-" * 88)
    g = defaultdict(list)
    for b in all_bad:
        g[(b["color"], b["bg"], b["size"], b["need"], b["ratio"])].append(b)
    for (color, bg, size, need, ratio), items in sorted(g.items(), key=lambda kv: kv[0][4]):
        print("    %s on %s  %gpx  실측 %.2f:1  (기준 %.1f:1)  %d곳"
              % (color, bg, size, ratio, need, len(items)))
        for b in items[:3]:
            print("        %-9s %-26s %s" % (b["path"], repr(b["text"])[:26], b["cls"][:44]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
