// ================================================================
// 클라이언트 번들 경계 계약 (2026-09-03 성능/구조 감사 신규)
//
// ## 무엇을 지키는가
//
// "기능을 계속 추가해도 **첫 화면이 무거워지지 않는다**" 를 코드로 고정한다.
// 이 세션의 실측이 그 반대 상태를 하나 찾아냈기 때문이다.
//
//   `src/components/SiteHeader.tsx` (8개 화면 전부가 쓰는 공용 헤더) 가
//   `@/lib/supabaseClient` 를 **정적 import** 했고, 그것이 `@supabase/ssr` 을 정적
//   import 했다. 그 결과 supabase-js 전체(realtime/storage/postgrest/functions 포함)가
//   **모든 라우트의 초기 번들**에 실렸다.
//
//       production build 실측: 242.9KB raw / 64.3KB gzip
//       `/search` 초기 JS 265.5KB gzip 중 이 하나가 24%
//       로그인하지 않은 첫 방문자도, 404 화면도 예외 없이 받아 갔다
//
//   그런데 이 라이브러리를 쓰는 코드는 **한 곳도 렌더 중에 부르지 않는다** —
//   전부 useEffect 안이거나 클릭 핸들러 안이다. hydration 을 막을 이유가 없었다.
//
// 고친 방식은 `@/lib/supabaseClient` 안에서 동적 import 로 늦추는 것이다.
// 그 구조가 다시 무너지면 **화면은 똑같이 잘 보이고 느려지기만 한다** — 사람이 눈으로
// 발견하기 어려운 종류의 회귀다. 그래서 검사로 잠근다.
//
// ## 왜 grep 이 아니라 import 그래프인가
//
// "SiteHeader 가 supabase 를 import 하지 않는다" 만 보면 한 칸만 우회해도 통과한다
// (헤더 -> 새 헬퍼 -> supabase). 지키려는 것은 파일 하나의 import 문이 아니라
// **클라이언트 경계에서 정적으로 도달 가능한 집합**이므로, 실제 그래프를 따라간다.
//
// ## 무엇을 검사하지 않는가
//
// 서버 컴포넌트/서버 액션/proxy 는 대상이 아니다 — 그쪽의 supabase 는 번들이 아니라
// Node 프로세스에 있다(`src/lib/supabaseServer.ts`, `src/proxy.ts`). 여기서 막으면
// 인증이 깨진다. 경계는 'use client' 다.
// ================================================================

import { test, describe } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join, dirname, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const ROOT = fileURLToPath(new URL('../', import.meta.url))
const SRC = join(ROOT, 'src')

/** 클라이언트 초기 번들에 **정적으로** 들어오면 안 되는 무거운 패키지.
 *  값의 근거는 실측이다(위 헤더 주석). 늦게 불러도 되는 것만 여기 적는다 —
 *  렌더에 꼭 필요한 라이브러리를 여기 넣으면 검사가 거짓말이 된다. */
const DEFERRED_ONLY_PACKAGES = ['@supabase/ssr', '@supabase/supabase-js']

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) out.push(...walk(path))
    else if (/\.(ts|tsx)$/.test(name)) out.push(path)
  }
  return out
}

function walkHtml(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) out.push(...walkHtml(path))
    else if (name.endsWith('.html')) out.push(path)
  }
  return out
}

/** 주석을 걷어낸 코드. 설명에 등장하는 패키지 이름이 위반으로 잡히면 안 된다. */
function code(path) {
  const raw = readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\//g, ' ')
  const NL = String.fromCharCode(10)
  return raw.split(NL).map((l) => l.replace(/(^|\s)\/\/.*$/, '$1')).join(NL)
}

const rel = (p) => p.slice(ROOT.length).split(sep).join('/')

/** 초기 번들에 실제로 들어가는 정적 import/export-from 의 명세자만 모은다.
 *
 *  세 가지는 **일부러 뺀다** — 넣으면 검사가 없는 무게를 있다고 말한다.
 *    - 동적 `import(...)`  : 별도 청크가 된다(이 파일이 지키려는 바로 그 방식이다)
 *    - `import type ...`   : 타입은 컴파일에서 지워진다(런타임 바이트 0)
 *    - `'use server'` 모듈 : 서버 액션은 클라이언트에 **참조 스텁**만 들어간다
 *                            (그래서 traversal 쪽에서 끊는다, 아래 staticClosure)
 */
function staticImports(src) {
  const out = []
  const re = /(?:^|[\s;}])((?:import|export)\s+(?:type\s+)?(?:[^'"();]*?\sfrom\s+)?)['"]([^'"]+)['"]/g
  for (const m of src.matchAll(re)) {
    const before = src.slice(Math.max(0, m.index - 40), m.index)
    if (/import\s*\($/.test(before)) continue
    if (/^(?:import|export)\s+type\b/.test(m[1].trim())) continue
    out.push(m[2])
  }
  return out
}

/** 상대/별칭 명세자를 실제 파일로. 외부 패키지면 null. */
function resolveLocal(spec, fromFile) {
  let base
  if (spec.startsWith('@/')) base = join(SRC, spec.slice(2))
  else if (spec.startsWith('.')) base = resolve(dirname(fromFile), spec)
  else return null
  const candidates = [base, base + '.ts', base + '.tsx',
    join(base, 'index.ts'), join(base, 'index.tsx')]
  for (const cand of candidates) {
    if (existsSync(cand) && statSync(cand).isFile()) return cand
  }
  return null
}

const FILES = walk(SRC)
const isClientModule = (p) => /^\s*['"]use client['"]/.test(readFileSync(p, 'utf8'))
// 서버 액션 모듈. 클라이언트가 import 해도 번들에 들어가는 것은 참조 스텁뿐이라
// 여기서 그래프를 끊는다 — 끊지 않으면 `login/page.tsx -> actions.ts -> supabaseServer`
// 처럼 **서버에만 있는 것**을 클라이언트 무게로 오인한다(실제로 오탐이 났다).
const isServerModule = (p) => /^\s*['"]use server['"]/.test(readFileSync(p, 'utf8'))
const CLIENT_ENTRIES = FILES.filter(isClientModule)

/** 클라이언트 경계에서 정적 import 만 따라가 닿는 모든 것.
 *  반환: { localFiles: Set, packages: Map<pkg, 경로문자열[]> } */
function staticClosure(entries) {
  const seen = new Set()
  const packages = new Map()
  const stack = entries.map((e) => ({ file: e, path: [e] }))
  while (stack.length) {
    const { file, path } = stack.pop()
    if (seen.has(file)) continue
    seen.add(file)
    for (const spec of staticImports(code(file))) {
      const local = resolveLocal(spec, file)
      if (local) {
        if (isServerModule(local)) continue
        stack.push({ file: local, path: [...path, local] })
      } else if (!spec.startsWith('node:')) {
        const pkg = spec.startsWith('@')
          ? spec.split('/').slice(0, 2).join('/')
          : spec.split('/')[0]
        if (!packages.has(pkg)) packages.set(pkg, [])
        packages.get(pkg).push([...path.map(rel), spec].join(' -> '))
      }
    }
  }
  return { localFiles: seen, packages }
}

describe('클라이언트 초기 번들 경계', () => {
  test('검사 대상을 실제로 찾았다 (공허하지 않다)', () => {
    assert.ok(FILES.length >= 15, `소스 ${FILES.length}개밖에 못 찾았다`)
    assert.ok(CLIENT_ENTRIES.length >= 10,
      `'use client' 모듈 ${CLIENT_ENTRIES.length}개밖에 못 찾았다`)
  })

  test('import 그래프가 실제로 여러 칸을 따라간다 (한 칸짜리 grep 이 아니다)', () => {
    // SiteHeader -> PrimaryNav 처럼 **엔트리가 아닌** 파일까지 닫힘에 들어와야
    // 우회(헤더 -> 새 헬퍼 -> supabase)를 잡을 수 있다.
    const { localFiles } = staticClosure(CLIENT_ENTRIES)
    const header = join(SRC, 'components', 'SiteHeader.tsx')
    assert.ok(localFiles.has(header), '공용 헤더가 클라이언트 닫힘에 없다')
    const indirect = [...localFiles].filter((f) => !CLIENT_ENTRIES.includes(f))
    assert.ok(indirect.length >= 3,
      `간접 도달 파일이 ${indirect.length}개뿐이다 — 그래프를 따라가지 못하고 있다`)
  })

  test('무거운 인증 SDK 가 초기 번들에 정적으로 들어오지 않는다', () => {
    const { packages } = staticClosure(CLIENT_ENTRIES)
    const violations = []
    for (const pkg of DEFERRED_ONLY_PACKAGES) {
      for (const chain of packages.get(pkg) ?? []) violations.push(chain)
    }
    assert.deepEqual(violations, [], [
      `클라이언트 초기 번들이 ${DEFERRED_ONLY_PACKAGES.join('/')} 를 정적으로 끌어온다.`,
      '실측 근거: 이 SDK 는 242.9KB raw / 64.3KB gzip 이고 모든 라우트가 함께 받는다.',
      '쓰는 곳은 전부 effect/핸들러 안이므로 lib/supabaseClient 의 동적 import 로 늦춰야 한다.',
      `경로: ${violations.join(' | ')}`,
    ].join(' '))
  })

  test('그 SDK 를 누군가는 쓰고 있다 (검사가 사어를 지키지 않는다)', () => {
    // 위 검사는 "아무도 안 쓴다" 로도 통과한다. 실제로 쓰이고 있고, 다만 늦게
    // 불린다는 것을 확인한다.
    const loader = join(SRC, 'lib', 'supabaseClient.ts')
    const body = code(loader)
    assert.match(body, /import\(\s*['"]@supabase\/ssr['"]\s*\)/,
      'supabaseClient 가 동적 import 로 SDK 를 불러오지 않는다')
    const users = FILES.filter((f) => f !== loader &&
      /from\s+['"]@\/lib\/supabaseClient['"]/.test(code(f)))
    assert.ok(users.length >= 5, `이 로더를 쓰는 화면이 ${users.length}개뿐이다`)
  })

  test('서버 쪽 supabase 는 막지 않는다 (경계를 잘못 그으면 인증이 깨진다)', () => {
    // proxy(모든 요청의 세션 갱신)와 서버 컴포넌트용 클라이언트는 정적 import 여야 한다.
    for (const p of [join(SRC, 'proxy.ts'), join(SRC, 'lib', 'supabaseServer.ts')]) {
      assert.match(code(p), /from\s+['"]@supabase\/ssr['"]/,
        `${rel(p)} 가 서버용 supabase 를 정적으로 쓰지 않는다`)
      assert.ok(!isClientModule(p), `${rel(p)} 가 'use client' 가 되어 있다`)
    }
  })
})

// ----------------------------------------------------------------
// production build 산출물 기준 예산. 빌드가 없으면 **판정하지 않는다**(skip).
// 위 소스 검사와 달리 이쪽은 supabase 뿐 아니라 **어떤 무거운 것이 들어와도** 잡는다.
// ----------------------------------------------------------------
const APP_OUT = join(ROOT, '.next', 'server', 'app')

/** 사전 렌더된 HTML 이 실제로 부르는 초기 JS 의 gzip 합계(KB). */
function firstLoadGzipKB(htmlPath) {
  const html = readFileSync(htmlPath, 'utf8')
  const all = [...html.matchAll(/src="(\/_next\/static\/chunks\/[^"]+\.js)"/g)].map((m) => m[1])
  // noModule 폴리필은 최신 브라우저가 받지 않는다 — 예산에서 뺀다.
  const nomodule = new Set(
    [...html.matchAll(/<script[^>]*src="(\/_next\/static\/chunks\/[^"]+\.js)"[^>]*noModule/gi)]
      .map((m) => m[1]))
  let total = 0
  for (const s of new Set(all)) {
    if (nomodule.has(s)) continue
    const file = join(ROOT, '.next', s.replace('/_next/', '').split('/').join(sep))
    if (existsSync(file)) total += gzipSync(readFileSync(file), { level: 6 }).length
  }
  return total / 1024
}

describe('production build 초기 JS 예산', () => {
  // 2026-09-03 실측 — **이 검사가 재는 그 값으로** 적는다(noModule 폴리필 38.5KB 제외).
  //
  //   고친 뒤(현재)  favorites 162.1 · favorites/import 162.0 · mypage 161.0 ·
  //                  properties/recent 160.4 · login 157.3 · _not-found 152.9 (KB gzip)
  //   고치기 전      favorites 220.1  (supabase-js 가 초기 번들에 있던 상태)
  //
  // 예산은 현재 최댓값(162.1) + 여유 23KB. 되돌아간 상태(220.1)를 35KB 차이로 넘긴다 —
  // 변이 검사로 실제 확인했다(정적 import 로 되돌린 뒤 빌드 -> 이 검사 실패).
  //
  // 프레임워크(react-dom + Next 런타임)만으로 137KB 라 이 숫자를 크게 낮출 수는 없다.
  // 잡으려는 것은 **새 라이브러리가 통째로 공용 경로에 들어오는** 일이다.
  const BUDGET_KB = 185

  test('사전 렌더된 라우트의 초기 JS 가 예산 안이다', (t) => {
    if (!existsSync(APP_OUT)) {
      t.skip('production build 산출물이 없다 — 판정 불가(통과가 아니다). npm run build 후 재실행')
      return
    }
    const htmls = walkHtml(APP_OUT)
    assert.ok(htmls.length >= 5,
      `사전 렌더 HTML 을 ${htmls.length}개밖에 못 찾았다 — 예산 검사가 공허하다`)
    const over = []
    for (const h of htmls) {
      const kb = firstLoadGzipKB(h)
      if (kb > BUDGET_KB) over.push(`${rel(h)} = ${kb.toFixed(1)}KB`)
    }
    assert.deepEqual(over, [], [
      `초기 JS 가 예산(${BUDGET_KB}KB gzip)을 넘었다: ${over.join(', ')}.`,
      '새 라이브러리가 공용 경로(layout/헤더/공용 컴포넌트)로 들어왔는지 먼저 본다.',
    ].join(' '))
  })
})
