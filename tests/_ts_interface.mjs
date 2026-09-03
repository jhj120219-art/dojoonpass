// ================================================================
// TS 선언 블록에서 {필드: (nullable, 선언문자열)} 를 읽는 공용 파서
// (2026-09-03 신설 — `_search_param_contract.mjs` 와 같은 계열의 테스트 헬퍼다.
//  파일명이 `_` 로 시작해 `tests/**/*.test.mjs` 글롭에 잡히지 않는다.)
//
// ## 왜 공용으로 뽑았나
//
// 같은 파서가 **두 벌**이 됐다.
//
//     tests/frontend-contract.test.mjs  tsTypes()   응답 값 ↔ 선언 대조 (표본, 살아 있는 API)
//     tests/source-contract.test.mjs    tsFields()  DB 스키마 ↔ 선언 대조 (전수, 정적)
//
// 둘은 **다른 것을 지키지만 같은 것을 읽는다.** 읽는 규칙이 갈라지면 한쪽만
// nullable 을 놓치고, 그때 두 검사가 서로를 눈감아 준다 — 이 저장소가
// `is_stale_contamination()` 에서 이미 한 번 겪은 모양이다(BUGS #224).
// 그래서 **읽는 규칙은 여기 한 곳에만** 둔다.
//
// ## 한계 (일부러 단순하게 둔다)
//
// TypeScript 파서가 아니라 줄 단위 정규식이다. 중첩 객체 리터럴은 걷어내고,
// 한 줄에 하나의 `이름: 타입` 만 읽는다. 이 저장소의 응답 타입은 전부 그 모양이라
// 충분하고, 진짜 파서를 붙이려면 새 의존성이 필요하다(승인 영역).
// 모양이 달라지면 `assertParses()` 가 먼저 붉어진다.
// ================================================================

import { promises as fs } from 'node:fs'

/**
 * `interface X {...}` / `type X = {...}` 본문의 필드를 읽는다.
 * @returns Map<필드명, { nullable: boolean, declared: string }>
 */
export async function readTsFields(file, name) {
  const src = await fs.readFile(file, 'utf8')
  const m = new RegExp(String.raw`(?:interface|type)\s+${name}\s*=?\s*\{`).exec(src)
  if (!m) throw new Error(`${file} 에서 ${name} 선언을 찾지 못했습니다`)

  // 중괄호 짝을 세어 본문 끝을 찾는다(정규식으로는 중첩을 못 센다).
  let depth = 1
  let i = m.index + m[0].length
  const start = i
  while (i < src.length && depth > 0) {
    if (src[i] === '{') depth++
    else if (src[i] === '}') depth--
    i++
  }

  // 중첩 객체 리터럴은 통째로 걷어낸다 — 안쪽 필드가 바깥 필드로 잘못 읽히면 안 된다.
  let body = src.slice(start, i - 1)
  for (;;) {
    const next = body.replace(/\{[^{}]*\}/g, '')
    if (next === body) break
    body = next
  }

  const out = new Map()
  for (const line of body.split('\n')) {
    const code = line.split('//')[0].trim()   // 주석의 예시가 필드로 읽히면 안 된다
    const km = /^([a-zA-Z_][a-zA-Z0-9_]*)(\??)\s*:\s*(.+?),?$/.exec(code)
    if (!km) continue
    const declared = km[3].trim().replace(/,$/, '')
    out.set(km[1], {
      // `?`(옵셔널) 도 "서버가 안 줄 수 있다"는 뜻이라 nullable 로 본다.
      nullable: km[2] === '?' || /\bnull\b|\bundefined\b/.test(declared),
      declared,
    })
  }
  return out
}

/**
 * 파서가 실제로 읽고 있는지 확인하는 자기 검증.
 * 두 호출부가 각각 "공허하지 않다"를 따로 적지 않도록 여기에 둔다.
 */
export async function assertParses(assert, file, name, { min = 3 } = {}) {
  const f = await readTsFields(file, name)
  assert.ok(f.size >= min, `${name} 에서 필드를 ${f.size}개밖에 못 읽었습니다`)
  return f
}
