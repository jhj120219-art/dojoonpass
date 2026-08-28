// 큰글씨(글자 크기) 설정 — **정본은 이 파일 하나다.**
//
// docs/BETA_RELEASE_CHECKLIST.md 의 접근성 표에 `[ ] 큰글씨 토글 UI` 가 미완으로
// 남아 있었다. 기술 기반은 Sprint 223 에 끝나 있었다 —
//
//     "큰글씨가 닿지 않는 글자(임의 px) 8곳 -> 0곳"
//     Tailwind v4 의 크기 토큰은 rem 기반(`--text-xs: .75rem`)
//
// 즉 **루트 글꼴 하나만 키우면 화면의 모든 글자가 따라 커진다.** 남은 것은
// 사용자가 그것을 켤 수단뿐이었고, 이 파일이 그 수단의 정본이다.
// (`test_frontend_accessibility.test_root_font_scaling_reaches_the_text` 가 그 전제를
//  계속 잠그고 있다 — 임의 px 이 한 곳이라도 생기면 붉어진다.)
//
// ## 왜 CSS 클래스가 아니라 `style.fontSize` 인가
//
// 배율을 CSS 에 적으면 이 표와 CSS 두 곳에 같은 수가 생긴다. 한쪽만 고치는 날이
// 오면 부트 스크립트와 토글이 서로 다른 크기를 말한다. 값은 여기 한 번만 적고
// 루트 엘리먼트에 직접 넣는다.

export const TEXT_SIZES = ['normal', 'large', 'xlarge'] as const

export type TextSize = (typeof TEXT_SIZES)[number]

export const DEFAULT_TEXT_SIZE: TextSize = 'normal'

/** localStorage 키. 서비스명을 접두사로 둬 다른 앱과 섞이지 않게 한다. */
export const TEXT_SIZE_STORAGE_KEY = 'kokchal.textSize'

/** `<html>` 에 붙는 표식. CSS 가 필요해지면 이것으로 걸면 된다(지금은 안 쓴다). */
export const TEXT_SIZE_ATTRIBUTE = 'data-text-size'

// 브라우저 기본 루트는 16px 이다.
//
// 상한을 125%(20px) 로 잡은 이유: 이 저장소는 **320px 폭 + 루트 글꼴 200%** 에서
// 헤더/버튼이 넘치는 것을 이미 실측하고 `flex-wrap` 으로 고쳤다(Sprint 240/247).
// 그보다 훨씬 안쪽이라 기존 레이아웃이 견디는 구간이다. 그 이상이 필요한 사용자는
// **브라우저 확대**를 쓴다 — 그쪽은 막혀 있지 않다(`user-scalable=no` 0곳).
export const TEXT_SIZE_SCALE: Record<TextSize, string> = {
  normal: '100%',
  large: '112.5%',
  xlarge: '125%',
}

/** 화면에 보이는 짧은 이름. 헤더가 좁으므로 한 글자로 둔다. */
export const TEXT_SIZE_SHORT_LABEL: Record<TextSize, string> = {
  normal: '가',
  large: '가',
  xlarge: '가',
}

/** 스크린리더/툴팁이 읽는 이름. 보이는 글자가 전부 "가"이므로 이것이 유일한 구분이다. */
export const TEXT_SIZE_LABEL: Record<TextSize, string> = {
  normal: '보통 글자 크기',
  large: '큰 글자',
  xlarge: '가장 큰 글자',
}

export function isTextSize(value: unknown): value is TextSize {
  return typeof value === 'string' && (TEXT_SIZES as readonly string[]).includes(value)
}

/**
 * 저장된 설정을 읽는다. 없거나 이상하면 기본값이다.
 *
 * `try` 로 감싸는 이유: 시크릿 모드/쿠키 차단 브라우저에서 `localStorage` 접근
 * 자체가 예외를 던진다. 글자 크기 설정 때문에 화면이 죽으면 안 된다.
 */
export function readStoredTextSize(): TextSize {
  try {
    const raw = window.localStorage.getItem(TEXT_SIZE_STORAGE_KEY)
    return isTextSize(raw) ? raw : DEFAULT_TEXT_SIZE
  } catch {
    return DEFAULT_TEXT_SIZE
  }
}

/** 루트 엘리먼트에 실제로 반영한다. 저장은 하지 않는다(호출부가 정한다). */
export function applyTextSize(size: TextSize): void {
  const root = document.documentElement
  root.style.fontSize = TEXT_SIZE_SCALE[size]
  root.setAttribute(TEXT_SIZE_ATTRIBUTE, size)
}

// ---------------------------------------------------------------------------
// 구독 — `useSyncExternalStore` 가 읽는 바깥 저장소
// ---------------------------------------------------------------------------
//
// 컴포넌트가 `useEffect` 안에서 `setState` 로 초기값을 맞추면 첫 렌더가 한 번
// 버려지고, 이 저장소의 lint 규칙(`react-hooks/set-state-in-effect`)도 막는다.
// 글자 크기는 **React 바깥(DOM 속성 + localStorage)에 사는 값**이므로 React 가
// 그런 값을 위해 준비한 방식으로 읽는다.
//
// 구독자를 두는 또 한 가지 이유: 토글이 두 곳에 놓이는 날(예: 마이페이지 설정)
// 한쪽에서 바꾼 것이 다른 쪽에 **즉시** 반영돼야 한다. 안 그러면 같은 화면에서
// 두 컨트롤이 서로 다른 값을 가리킨다.
const listeners = new Set<() => void>()

export function subscribeTextSize(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/**
 * 지금 화면에 **실제로 적용된** 크기.
 *
 * `localStorage` 가 아니라 루트 엘리먼트를 먼저 보는 이유: 부트 스크립트가 이미
 * 반영해 둔 값이 곧 사용자가 보고 있는 크기다. 저장은 됐는데 반영이 안 된 상태를
 * "적용됐다"고 말하면 버튼의 눌린 표시가 화면과 어긋난다.
 */
export function getTextSizeSnapshot(): TextSize {
  const applied = document.documentElement.getAttribute(TEXT_SIZE_ATTRIBUTE)
  if (isTextSize(applied)) return applied
  return readStoredTextSize()
}

/** 서버 렌더에는 DOM 도 저장소도 없다. 기본값으로 그리고, 부트 스크립트가 덮는다. */
export function getTextSizeServerSnapshot(): TextSize {
  return DEFAULT_TEXT_SIZE
}

/** 반영 + 저장 + 구독자 통지. 저장이 막혀 있어도 **이번 화면에는 적용된다.** */
export function setTextSize(size: TextSize): void {
  applyTextSize(size)
  try {
    window.localStorage.setItem(TEXT_SIZE_STORAGE_KEY, size)
  } catch {
    // 저장만 실패한 것이다 — 새로고침하면 기본값으로 돌아가지만 지금은 커져 있다.
  }
  listeners.forEach((listener) => listener())
}

/**
 * 첫 페인트 **전에** 실행할 스크립트. `layout.tsx` 가 `<head>` 에 넣는다.
 *
 * 없으면 기본 크기로 한 번 그려진 뒤 커져서 **글자가 튀어 보인다**(FOUC).
 * React 가 마운트되기 전이라 이 모듈을 import 할 수 없으므로 문자열이지만,
 * **값은 위 상수에서 만들어 낸다** — 배율을 두 곳에 적지 않는다.
 */
export function textSizeBootScript(): string {
  const scale = JSON.stringify(TEXT_SIZE_SCALE)
  return (
    '(function(){try{' +
    `var m=${scale},k=${JSON.stringify(TEXT_SIZE_STORAGE_KEY)};` +
    'var v=window.localStorage.getItem(k);' +
    'if(!m[v])return;' +
    'var r=document.documentElement;' +
    'r.style.fontSize=m[v];' +
    `r.setAttribute(${JSON.stringify(TEXT_SIZE_ATTRIBUTE)},v);` +
    '}catch(e){}})()'
  )
}
