// ================================================================
// Supabase 경계 계약 — Sprint 272 신규 (docs/BUGS.md #17 종결과 함께)
//
// `docs/CLAUDE.md` Architecture:
//
//   "Supabase is used only for auth/session — auction data always comes from
//    the Python API, never queried from Supabase directly."
//
// 이 규칙이 깨졌을 때 무슨 일이 났는지 저장소가 기록하고 있다(#17/#34).
//
//   `/properties` 목록이 Supabase `properties` 테이블(시드 5행)을 직접 조회하면서
//   카드 링크는 `/properties/{id}`(FastAPI `auction_item`)로 보냈다. 두 id 는 서로
//   다른 시스템이 독립적으로 채번하므로 **404 도 나지 않고 전혀 다른 물건이 열렸다** —
//   실측: "강남구 역삼동 아파트"를 누르면 "관악구 난곡로66가길 2층202호"가 열림.
//
// 조용한 오답이다. 오류도 빈 화면도 아니라 사용자가 틀렸다는 것을 알 수 없다.
//
// 2026-08-11 Sprint 51 이 그 화면을 `/` 로 redirect 시켜 해소했고, 2026-08-28 에
// 실측으로 재확인했다(Supabase 직접조회 0건 / `formatPrice` 정의 1곳 /
// 로그아웃은 공용 헤더). **그런데 그 규칙을 지키는 검사가 하나도 없었다** —
// 누가 다시 화면에서 테이블을 조회해도 알려 줄 것이 없다.
//
// 그래서 규칙 쪽을 고정한다. Supabase 클라이언트를 쓰는 것 자체는 정상이고
// (`auth.getSession()` 등), **데이터 테이블 조회**만 막는다.
// ================================================================

import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

// Windows 에서 `URL.pathname` 은 `/C:/...` 이라 그대로 쓰면 경로가 어긋난다.
const SRC = fileURLToPath(new URL('../src/', import.meta.url))

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) out.push(...walk(path))
    else if (/\.(ts|tsx)$/.test(name)) out.push(path)
  }
  return out
}

const FILES = walk(SRC)

/** 주석을 걷어낸 코드만 본다 — 설명에 등장하는 예시가 위반으로 잡히면 안 된다. */
function code(path) {
  const raw = readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\//g, ' ')
  const NEWLINE = String.fromCharCode(10)
  return raw
    .split(NEWLINE)
    .map((line) => line.replace(/(^|\s)\/\/.*$/, '$1'))
    .join(NEWLINE)
}

// 구분자를 `/` 로 통일한다 — Windows 는 `\` 를 쓰고, 그러면 기대값이 OS 마다 갈린다.
const rel = (p) => p.slice(SRC.length).split(sep).join('/')

describe('Supabase 는 인증에만 쓴다', () => {
  test('검사 대상 소스를 실제로 찾았다 (공허하지 않다)', () => {
    assert.ok(FILES.length >= 15, `소스 ${FILES.length}개밖에 못 찾았다`)
  })

  test('화면이 Supabase 데이터 테이블을 직접 조회하지 않는다', () => {
    // `.from('...')` 은 PostgREST 데이터 질의다. auth 는 `.auth.xxx()` 를 쓴다.
    const offenders = []
    for (const path of FILES) {
      const body = code(path)
      for (const m of body.matchAll(/\.from\(\s*['"`]([^'"`]+)['"`]/g)) {
        offenders.push(`${rel(path)} -> from('${m[1]}')`)
      }
    }
    assert.deepEqual(offenders, [], [
      'Supabase 테이블을 화면에서 직접 조회하고 있다.',
      '경매 데이터는 항상 Python API 를 거쳐야 한다(docs/CLAUDE.md).',
      '#17/#34: id 채번이 달라 404 도 없이 엉뚱한 물건이 열렸다.',
    ].join(' '))
  })

  test('Supabase 클라이언트는 세션/인증 용도로만 불린다', () => {
    // 실제로 무엇에 쓰는지 확인한다 — 위 검사가 "쓰지 않는다"로 공허해지지 않게.
    const uses = []
    for (const path of FILES) {
      const body = code(path)
      if (!body.includes('createClient')) continue
      for (const m of body.matchAll(/supabase\s*\.\s*(\w+)/g)) uses.push(m[1])
    }
    assert.ok(uses.length > 0, 'Supabase 를 쓰는 화면을 하나도 못 찾았다')
    const allowed = new Set(['auth'])
    const bad = [...new Set(uses)].filter((u) => !allowed.has(u))
    assert.deepEqual(bad, [], `허용되지 않은 Supabase 사용: ${bad.join(', ')}`)
  })

  test('레거시 `/properties` 는 목록을 그리지 않고 `/` 로 보낸다 (#34)', () => {
    const body = code(join(SRC, 'app', 'properties', 'page.tsx'))
    assert.match(body, /redirect\(\s*['"]\/['"]\s*\)/)
    assert.doesNotMatch(body, /createClient/, '이 화면은 다시 데이터를 조회하면 안 된다')
  })

  test('금액 포맷 정의가 한 곳뿐이다 (#17 의 부수 문제)', () => {
    // 화면마다 따로 정의하면 같은 금액이 화면마다 다르게 보인다
    // (#17 실측: 지역 구현이 500만원을 "0.1억"으로 그렸다).
    const defs = []
    for (const path of FILES) {
      const body = code(path)
      if (/(function|const)\s+formatPrice\b/.test(body)) defs.push(rel(path))
    }
    assert.deepEqual(defs, ['lib/format.ts'], `formatPrice 정의가 여러 곳이다: ${defs}`)
  })
})
