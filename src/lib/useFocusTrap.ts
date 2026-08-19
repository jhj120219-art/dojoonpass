'use client'

import { useEffect, useRef } from 'react'

// 모달 안에서 실제로 포커스를 받을 수 있는 것들.
// `:disabled`를 제외하는 이유 — 문서 뷰어의 쪽 이동/확대 버튼은 경계에서 disabled가 되는데,
// 그 순간 Tab이 "아무 데도 아닌 곳"에 멈추면 안 된다. 그래서 목록은 Tab을 누를 때마다
// 다시 계산한다(모달이 열려 있는 동안 버튼이 나타나고 사라지기 때문이다).
const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

/**
 * 모달이 열려 있는 동안 **키보드 포커스를 모달 안에 가둔다**(2026-08-19 Sprint 223, BUGS #151).
 *
 * ## 왜 필요한가 — 실측한 결함
 *
 * 상세 화면(`/properties/505`)에서 사진 라이트박스를 연 뒤 실제로 잰 값이다.
 *
 *     모달을 연 직후 document.activeElement   "대표 사진 크게 보기"(모달 **뒤**의 버튼)
 *     모달 안의 포커스 가능 요소               3개
 *     화면 전체의 포커스 가능 요소             24개   -> 21개가 오버레이 뒤에 그대로 살아 있다
 *     Tab 한 번                                "전경도 1번 크게 보기"(top 415, left 346)
 *                                              = 검은 오버레이에 완전히 가려진 버튼
 *     Escape 로 닫은 뒤                        포커스가 헤매던 자리에 그대로 (여는 버튼으로 안 돌아옴)
 *
 * 즉 키보드 사용자는 모달을 열자마자 **자기가 어디에 있는지 알 수 없고**, Tab을 누르면
 * 보이지 않는 버튼 위에 서게 되며, 거기서 Enter를 누르면 의도하지 않은 동작이 일어난다.
 * `aria-modal="true"`(Sprint 221)는 스크린리더에게만 "뒤를 읽지 말라"고 말할 뿐,
 * **실제 Tab 이동은 막지 못한다.** 그건 브라우저의 순차 포커스 규칙이라 코드로 잡아야 한다.
 *
 * ## 무엇을 하는가 — 세 가지뿐이고, 픽셀은 하나도 바꾸지 않는다
 *
 *   1. 열릴 때  모달 안 첫 번째 포커스 가능 요소로 포커스를 옮긴다(둘 다 "닫기" 버튼이다).
 *   2. 열린 동안 Tab / Shift+Tab이 모달 밖으로 나가지 않고 양끝에서 순환한다.
 *   3. 닫힐 때  **열기 전에 포커스가 있던 요소로 되돌린다.** 그 요소가 그 사이에 사라졌으면
 *              (예: 목록이 다시 그려짐) 억지로 되돌리지 않는다 — 없는 곳에 포커스를 주면
 *              브라우저가 body로 떨어뜨려 오히려 위치를 더 잃는다.
 *
 * 반환값은 모달 컨테이너에 달 ref다. `active`가 false면 아무것도 하지 않는다.
 *
 * ## 고치고 난 뒤 실측한 값 (실브라우저, 진짜 마우스 클릭·진짜 Tab)
 *
 *     사진 라이트박스 열기      포커스 -> '닫기'(모달 안)
 *     Tab x3                  닫기 -> 이전 사진 -> 다음 사진 -> 닫기 (순환, 밖으로 안 나간다)
 *     Shift+Tab               닫기 -> 다음 사진 (뒤로도 순환)
 *     Escape                  모달 닫힘 + 포커스가 **여는 버튼 바로 그 노드**로 복귀
 *     문서 뷰어도 동일    열기 -> '닫기', Escape -> '매각물건명세서' 버튼으로 복귀
 *     밖으로 포커스 강제    '로그아웃'(모달 밖)에 주자 곳바로 '닫기'로 되돌아옴
 *
 * ★ 측정 도구가 한 번 거짓말을 했다 — 탭이 **보이지 않는 상태**(visibilityState hidden)에서
 * `element.focus()` 를 부르면 activeElement 는 바뀌지만 **focus/focusin 이벤트가 전혀
 * 발생하지 않는다**(직접 확인: 직접 달아 둔 focusin 리스너가 0회 호출됐다).
 * 그 상태에서 재어 뷰어를 열어 보고 "처음 열 때만 포커스가 안 간다"는 **없는 결함**을
 * 만들 뻔했다. 탭을 보이게 하고 **진짜 마우스 클릭**으로 다시 재면 첫 열기부터 정상이었다.
 * 포커스는 창 포커스 상태에 의존하므로, 보이지 않는 탭에서 쟰 값을 근거로 쓰면 안 된다.
 */
export function useFocusTrap<T extends HTMLElement>(active: boolean) {
  const containerRef = useRef<T | null>(null)

  useEffect(() => {
    if (!active) return
    const container = containerRef.current
    if (!container) return

    // 열기 직전의 포커스. 닫을 때 여기로 되돌린다.
    const previous = document.activeElement as HTMLElement | null

    // 보이는 것만 센다. `offsetParent`는 position:fixed 조상 아래에서 신뢰할 수 없으므로
    // (모달 자체가 fixed다) 실제 박스가 그려졌는지를 본다.
    function focusable(): HTMLElement[] {
      return Array.from(container!.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.getClientRects().length > 0
      )
    }

    const first = focusable()[0]
    if (first) {
      first.focus()
    } else {
      // 포커스할 것이 하나도 없는 모달이라면 컨테이너 자체를 받게 한다 —
      // 그래야 스크린리더가 모달 안으로 들어오고, Tab이 뒤로 새지 않는다.
      container.tabIndex = -1
      container.focus()
    }

    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== 'Tab') return
      const list = focusable()
      if (list.length === 0) {
        e.preventDefault()
        return
      }
      const current = document.activeElement as HTMLElement | null
      const index = current ? list.indexOf(current) : -1
      if (e.shiftKey) {
        // 첫 요소에서 Shift+Tab -> 마지막으로. 모달 밖(index === -1)에서 들어온 경우도 같다.
        if (index <= 0) {
          e.preventDefault()
          list[list.length - 1].focus()
        }
      } else if (index === -1 || index === list.length - 1) {
        e.preventDefault()
        list[0].focus()
      }
    }

    // Tab 이 아닌 경로로 포커스가 모달 밖으로 나가는 것도 되돌린다.
    // Tab 만 막으면 모든 경로를 막은 것처럼 보이지만 아니다 — 오버레이는 화면을 덮을 뿐
    // 뒤의 버튼을 DOM 에서 지우지 않으므로, 모달이 닫히지 않은 채 포커스가 그쪽으로
    // 옮겨가면 사용자는 **보이지 않는 컨트롤 위에** 서 게 된다.
    // (실측: 모달이 열린 상태에서 밖의 '로그아웃' 버튼에 포커스를 주자 곳바로
    //  '닫기' 로 되돌아왔다.) iframe 등 모달 **안**의 요소는 그대로 허용된다.
    function onFocusIn(e: FocusEvent) {
      const target = e.target as Node | null
      if (target && container!.contains(target)) return
      const list = focusable()
      if (list.length > 0) {
        list[0].focus()
      } else {
        container!.tabIndex = -1
        container!.focus()
      }
    }

    // capture 단계에 단다 — 모달 안쪽 요소가 Tab을 먼저 처리해 버려도 경계는 지켜야 한다.
    document.addEventListener('keydown', onKeyDown, true)
    document.addEventListener('focusin', onFocusIn, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      // 되돌리기 **전에** 감시를 끔는다. 순서가 바뀌면 복귀하는 포커스를
      // 자기 감시기가 다시 모달 안으로 끌고 들어온다.
      document.removeEventListener('focusin', onFocusIn, true)
      if (previous && document.contains(previous)) previous.focus()
    }
  }, [active])

  return containerRef
}
