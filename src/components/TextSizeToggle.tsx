'use client'

import { useSyncExternalStore } from 'react'
import {
  TEXT_SIZES,
  TEXT_SIZE_LABEL,
  TEXT_SIZE_SHORT_LABEL,
  getTextSizeServerSnapshot,
  getTextSizeSnapshot,
  setTextSize,
  subscribeTextSize,
  type TextSize,
} from '@/lib/textSize'

// 큰글씨 토글 — `docs/BETA_RELEASE_CHECKLIST.md` 접근성 표의 `[ ] 큰글씨 토글 UI`.
//
// 값·배율·저장키·구독은 **하나도 여기에 적지 않는다.** 전부 `@/lib/textSize` 가
// 갖고 있고, `layout.tsx` 의 부트 스크립트도 같은 곳에서 만들어진다 — 두 곳에
// 적으면 "새로고침 직후 크기"와 "토글이 말하는 크기"가 갈리는 날이 온다.
//
// ## 왜 세 단계인가
//
// 켜고 끄는 두 단계면 "조금만 크게"가 없다. 세 단계는 100% / 112.5% / 125% 이고,
// 그 이상이 필요하면 **브라우저 확대**가 있다 — 이 저장소는 확대를 막는 뷰포트
// 설정을 두지 않으며 `test_zoom_is_not_disabled` 가 그것을 잠그고 있다.
//
// (그 검사는 소스 원문에서 금지 토큰을 찾으므로, 여기서도 그 토큰을 글자 그대로
//  적지 않는다. 설명하려다 검사에 걸린 적이 있다 — 2026-08-28.)
//
// ## 접근성
//
// 보이는 글자가 셋 다 "가"라서 시각적으로는 크기로만 구분된다. 그래서 스크린리더용
// 이름(`aria-label`)과 눌린 상태(`aria-pressed`)를 각 버튼이 직접 갖는다.
// 묶음에는 `role="group"` + 이름을 둬 "글자 크기"라는 맥락을 준다.
export default function TextSizeToggle() {
  // 글자 크기는 **React 바깥**(루트 엘리먼트 + localStorage)에 사는 값이다.
  // 부트 스크립트가 첫 페인트 전에 이미 반영해 두므로, 여기서는 그 값을 읽기만 한다
  // (`useEffect` 로 초기값을 맞추면 첫 렌더가 버려지고 lint 규칙도 막는다).
  const size = useSyncExternalStore(
    subscribeTextSize,
    getTextSizeSnapshot,
    getTextSizeServerSnapshot,
  )

  return (
    <div
      role="group"
      aria-label="글자 크기"
      className="flex items-center rounded-lg border border-gray-200"
    >
      {TEXT_SIZES.map((option: TextSize, index: number) => {
        const active = option === size
        return (
          <button
            key={option}
            type="button"
            onClick={() => setTextSize(option)}
            aria-pressed={active}
            aria-label={TEXT_SIZE_LABEL[option]}
            title={TEXT_SIZE_LABEL[option]}
            className={[
              // 탭 타깃 44px(WCAG 2.5.8). 기존 화면의 미달 컨트롤을 여기서 고치지는
              // 않지만, **새로 만드는 것**은 크기를 고를 수 있다. 하필 큰글씨가
              // 필요한 사용자를 위한 컨트롤이 손가락에 안 잡히면 앞뒤가 맞지 않는다.
              'min-h-11 min-w-11 px-2 leading-none font-medium transition-colors',
              'flex items-center justify-center',
              // 버튼마다 글자를 키워 **무엇을 고르는지 눈으로 보이게** 한다.
              // 사다리를 `text-sm` 에서 시작한다. `text-xs` 로 시작하면 저장소의
              // 작은글씨 래칫(상한 119)을 한 칸 밀어내는데, **작은 글자를 벗어나게
              // 해 주는 컨트롤이 작은 글자를 늘리는 것**은 앞뒤가 맞지 않는다.
              // 탭 타깃도 그만큼 커진다.
              index === 0 ? 'text-sm' : index === 1 ? 'text-base' : 'text-lg',
              active ? 'bg-blue-500 text-white' : 'text-gray-700 active:bg-gray-100',
              index === 0 ? 'rounded-l-lg' : '',
              index === TEXT_SIZES.length - 1 ? 'rounded-r-lg' : '',
            ].join(' ')}
          >
            {TEXT_SIZE_SHORT_LABEL[option]}
          </button>
        )
      })}
    </div>
  )
}
