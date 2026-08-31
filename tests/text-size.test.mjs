// ================================================================
// 큰글씨(글자 크기) 회귀 테스트 — Sprint 271 신규
//
// `docs/BETA_RELEASE_CHECKLIST.md` 접근성 표에 `[ ] 큰글씨 토글 UI` 가 **미완**으로
// 남아 있었다. 기술 기반은 Sprint 223 에 끝나 있었고(임의 px 글자 8곳 -> 0곳,
// Tailwind 크기 토큰이 rem), 없던 것은 **사용자가 켤 수단**뿐이었다.
//
// 이 파일은 그 수단의 순수 로직을 고정한다. 화면 조립(`TextSizeToggle`/`SiteHeader`)은
// `source-contract` 쪽이, 실제 확대는 `test_frontend_accessibility.py` 의
// `test_root_font_scaling_reaches_the_text` 가 계속 잠근다.
//
// ★ 브라우저 실측(2026-08-28, next dev + 실제 Chrome):
//     root 16px -> 20px / 본문 12px -> 15px
//     새로고침 후에도 유지(data-text-size=xlarge, aria-pressed 이동)
//     상세 화면으로 전파, 문서 가로 스크롤 없음
//   이 파일은 그 동작의 **근거가 되는 값**이 흔들리지 않게 한다.
// ================================================================

import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import {
  TEXT_SIZES,
  DEFAULT_TEXT_SIZE,
  TEXT_SIZE_SCALE,
  TEXT_SIZE_LABEL,
  TEXT_SIZE_SHORT_LABEL,
  TEXT_SIZE_STORAGE_KEY,
  TEXT_SIZE_ATTRIBUTE,
  isTextSize,
  textSizeBootScript,
} from '../src/lib/textSize.ts'

describe('단계 정의 — 정상', () => {
  test('세 단계이고 기본은 보통이다', () => {
    assert.deepEqual([...TEXT_SIZES], ['normal', 'large', 'xlarge'])
    assert.equal(DEFAULT_TEXT_SIZE, 'normal')
    assert.ok(TEXT_SIZES.includes(DEFAULT_TEXT_SIZE))
  })

  test('기본값은 100% — 아무 설정도 안 한 사용자의 화면이 지금과 같아야 한다', () => {
    assert.equal(TEXT_SIZE_SCALE.normal, '100%')
  })

  test('단계마다 실제로 커진다 (같은 값이 두 번 나오지 않는다)', () => {
    const pct = TEXT_SIZES.map((s) => parseFloat(TEXT_SIZE_SCALE[s]))
    for (let i = 1; i < pct.length; i += 1) {
      assert.ok(pct[i] > pct[i - 1], `${TEXT_SIZES[i]} 가 앞 단계보다 크지 않다: ${pct}`)
    }
  })

  test('모든 단계에 배율과 두 가지 이름이 있다', () => {
    for (const size of TEXT_SIZES) {
      assert.ok(TEXT_SIZE_SCALE[size], `${size} 배율 없음`)
      assert.ok(TEXT_SIZE_LABEL[size], `${size} 스크린리더 이름 없음`)
      assert.ok(TEXT_SIZE_SHORT_LABEL[size], `${size} 표시 글자 없음`)
    }
  })

  test('스크린리더 이름은 서로 다르다 — 보이는 글자가 셋 다 "가"라서 이것이 유일한 구분이다', () => {
    const labels = TEXT_SIZES.map((s) => TEXT_SIZE_LABEL[s])
    assert.equal(new Set(labels).size, labels.length, labels.join(' / '))
  })
})

describe('경계값 — 레이아웃이 견디는 범위', () => {
  test('최대 배율이 125% 를 넘지 않는다', () => {
    // 이 저장소는 320px 폭 + 루트 글꼴 200% 에서 헤더/버튼이 넘치는 것을 실측하고
    // flex-wrap 으로 고쳤다(Sprint 240/247). 그보다 훨씬 안쪽으로 둔다.
    // 더 큰 배율이 필요한 사용자는 브라우저 확대를 쓴다(막혀 있지 않다).
    const max = Math.max(...TEXT_SIZES.map((s) => parseFloat(TEXT_SIZE_SCALE[s])))
    assert.ok(max <= 125, `최대 배율 ${max}% 는 실측으로 확인된 안전 범위를 넘는다`)
  })

  test('최소 배율이 100% 아래로 내려가지 않는다 — 이 기능은 키우는 기능이다', () => {
    const min = Math.min(...TEXT_SIZES.map((s) => parseFloat(TEXT_SIZE_SCALE[s])))
    assert.equal(min, 100)
  })
})

describe('오류/이상 입력 — 화면이 죽지 않는다', () => {
  test('모르는 값은 단계로 인정하지 않는다', () => {
    for (const bad of ['huge', '', 'NORMAL', null, undefined, 0, 1, {}, [], 'large ']) {
      assert.equal(isTextSize(bad), false, `${JSON.stringify(bad)} 를 단계로 받아들였다`)
    }
  })

  test('아는 값은 전부 인정한다', () => {
    for (const size of TEXT_SIZES) assert.equal(isTextSize(size), true)
  })
})

describe('부트 스크립트 — 새로고침 후에도 유지된다', () => {
  const script = textSizeBootScript()

  test('배율표를 스크립트에 다시 적지 않는다 (정본은 한 곳)', () => {
    // 값이 두 곳에 있으면 "새로고침 직후 크기"와 "토글이 말하는 크기"가 갈린다.
    for (const size of TEXT_SIZES) {
      assert.ok(script.includes(TEXT_SIZE_SCALE[size]),
        `${size}(${TEXT_SIZE_SCALE[size]}) 가 부트 스크립트에 없다`)
    }
    assert.ok(script.includes(TEXT_SIZE_STORAGE_KEY))
    assert.ok(script.includes(TEXT_SIZE_ATTRIBUTE))
  })

  test('저장소 접근이 막혀도 예외를 밖으로 내보내지 않는다', () => {
    // 시크릿 모드/쿠키 차단에서 localStorage 접근 자체가 던진다.
    // 글자 크기 때문에 첫 페인트가 죽으면 화면 전체를 잃는다.
    assert.ok(script.includes('try{') && script.includes('catch'), script.slice(0, 120))
  })

  test('모르는 저장값이면 아무것도 하지 않는다 (기본 크기 유지)', () => {
    assert.ok(script.includes('if(!m[v])return;'), script)
  })

  test('실제로 실행해 보면 루트에 배율과 표식을 남긴다', () => {
    for (const size of TEXT_SIZES) {
      const root = { style: {}, _attrs: {}, setAttribute(k, v) { this._attrs[k] = v } }
      const store = { [TEXT_SIZE_STORAGE_KEY]: size }
      const fakeWindow = { localStorage: { getItem: (k) => store[k] ?? null } }
      const fakeDocument = { documentElement: root }
      new Function('window', 'document', script)(fakeWindow, fakeDocument)
      assert.equal(root.style.fontSize, TEXT_SIZE_SCALE[size], size)
      assert.equal(root._attrs[TEXT_SIZE_ATTRIBUTE], size, size)
    }
  })

  test('저장값이 이상하면 루트를 건드리지 않는다 — 경계값', () => {
    const root = { style: {}, _attrs: {}, setAttribute(k, v) { this._attrs[k] = v } }
    const fakeWindow = { localStorage: { getItem: () => 'gigantic' } }
    new Function('window', 'document', script)(fakeWindow, { documentElement: root })
    assert.equal(root.style.fontSize, undefined)
    assert.deepEqual(root._attrs, {})
  })

  test('저장소가 던져도 조용히 넘어간다 — 오류', () => {
    const root = { style: {}, _attrs: {}, setAttribute(k, v) { this._attrs[k] = v } }
    const fakeWindow = { localStorage: { getItem() { throw new Error('blocked') } } }
    assert.doesNotThrow(() =>
      new Function('window', 'document', script)(fakeWindow, { documentElement: root }))
    assert.equal(root.style.fontSize, undefined)
  })
})

// ---------------------------------------------------------------------------
// 배선 — "버튼만 존재"를 허용하지 않는다
// ---------------------------------------------------------------------------
//
// 순수 로직이 아무리 맞아도 화면에 연결되지 않으면 사용자는 쓸 수 없다.
// 이 저장소는 같은 부류를 이미 겪었다 — 선언은 검사되는데 **배선은 검사되지 않는**
// 자리(BUGS: 파라미터를 선언만 하고 목록에서 빼면 소스 검사 36건이 전부 통과했다).
import { readFileSync } from 'node:fs'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')

// 주석을 걷어낸 **코드만** 본다.
//
// 처음에는 원문 그대로 검사했더니 "배율을 직접 적지 않는다"가 주석의
// `100% / 112.5% / 125%` 를 잡아 붉어졌다 — 코드는 멀쩡한데 설명이 걸린 것이다.
// `test_frontend_accessibility.py` 가 `_strip_comments` 를 두는 이유와 같다.
const NEWLINE = String.fromCharCode(10)
const code = (p) => {
  // ★ CRLF 를 먼저 고른다. 이 저장소는 core.autocrlf=true 라 작업트리가 CRLF 인데,
  //   아래 split(NEWLINE) 은 개행문자로만 자른다 -> 각 줄 끝에 캐리지리턴이 남는다.
  //   JS 정규식에서 '.' 은 그 문자를 못 먹고, 플래그 없는 '$' 는 문자열 끝에서만
  //   맞는다 -> 줄주석 제거 정규식이 **한 줄도 안 지워졌다.**
  //   그래서 이 헬퍼가 주석을 못 걷어낸 채로 돌고 있었다(2026-09-01 확인).
  //   그 결과 이 파일의 code() 기반 검사 2개가 설명 주석을 집어 **거짓 실패**했다.
  const withoutBlocks = read(p).replace(/\r\n/g, NEWLINE).replace(/\/\*[\s\S]*?\*\//g, ' ')
  const lines = withoutBlocks.split(NEWLINE)
  const stripped = lines.map((line) => line.replace(/(^|\s)\/\/.*$/, '$1'))
  return stripped.join(NEWLINE)
}

describe('배선 — 사용자가 실제로 쓸 수 있는가', () => {
  test('공용 헤더가 토글을 그린다 (모든 주요 화면이 이 헤더를 쓴다)', () => {
    const header = read('../src/components/SiteHeader.tsx')
    assert.match(header, /import TextSizeToggle/)
    assert.match(header, /<TextSizeToggle\s*\/>/)
  })

  test('layout 이 첫 페인트 전에 설정을 반영한다 (새로고침 시 글자가 튀지 않는다)', () => {
    const layout = read('../src/app/layout.tsx')
    assert.match(layout, /textSizeBootScript/)
    assert.match(layout, /<head>/)
  })

  test('토글이 값을 스스로 정의하지 않는다 — 정본은 lib/textSize 하나다', () => {
    const toggle = code('../src/components/TextSizeToggle.tsx')
    assert.match(toggle, /from '@\/lib\/textSize'/)
    // 배율(%)이나 저장키를 컴포넌트가 직접 적으면 두 벌이 된다.
    assert.doesNotMatch(toggle, /\d+(\.\d+)?%/, '토글이 배율을 직접 적고 있다')
    assert.doesNotMatch(toggle, new RegExp(TEXT_SIZE_STORAGE_KEY.replace('.', '\.')),
      '토글이 저장키를 직접 적고 있다')
  })

  test('토글이 접근성 이름과 눌린 상태를 낸다', () => {
    const toggle = read('../src/components/TextSizeToggle.tsx')
    assert.match(toggle, /role="group"/)
    assert.match(toggle, /aria-label="글자 크기"/)
    assert.match(toggle, /aria-pressed=/)
    assert.match(toggle, /aria-label=\{TEXT_SIZE_LABEL/)
  })

  test('작은글씨 래칫을 밀어내지 않는다 — 작은 글자를 벗어나게 해 주는 컨트롤이 작은 글자를 늘리면 앞뒤가 안 맞는다', () => {
    const toggle = code('../src/components/TextSizeToggle.tsx')
    assert.doesNotMatch(toggle, /\btext-xs\b/)
  })
})
