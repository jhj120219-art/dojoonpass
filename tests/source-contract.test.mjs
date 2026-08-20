// ================================================================
// 소스 계약 테스트 (2026-08-11 Sprint 53 신규 — frontend-contract.test.mjs에서 분리)
//
// **이 파일은 서버가 필요 없다.** 파일 내용만 읽어 확정된 계약이 코드에 남아 있는지 확인한다.
//
// 왜 분리했나
// -----------------------------------------------------------------
// `frontend-contract.test.mjs`는 `before()`에서 dev 서버 응답을 확인하고 첫 화면 HTML을
// 받아 둔다. Node 테스트 러너는 `before()`가 실패하면 **그 파일의 모든 테스트를 취소**하므로,
// 서버가 잠깐 죽어 있으면 서버와 아무 상관 없는 소스 레벨 검사까지 함께 사라졌다
// (Sprint 50이 기술부채로 기록한 항목). 실제로 빌드 중 dev 서버를 내렸을 때
// "45개 중 0개 통과 / 0개 실패"라는, 원인 파악이 어려운 결과가 나왔다.
//
// 서버 의존 검사는 그대로 두고 **소스만 읽는 검사만** 이 파일로 옮겼다.
// 이제 서버가 꺼져 있어도 이 파일은 정상적으로 통과/실패를 보고한다.
// (`npm run test:frontend`가 tests/**/*.test.mjs를 전부 실행하므로 실행 방법은 그대로다.)
// ================================================================

import { test, describe } from 'node:test'
import assert from 'node:assert/strict'

describe('검색 실행이 현재 pathname을 유지한다 (MASTER_SPEC §8.2) — 소스 계약', () => {
  test('검색 Form이 /search로 하드코딩 push하지 않는다', () => {
    // 실제 push 대상은 클라이언트 런타임 값이라 HTTP로 직접 볼 수 없다. 대신 회귀의
    // 근원이었던 하드코딩이 소스에 남아있지 않은지 정적으로 확인한다.
    // (소스 검사는 이 파일에서 유일한 예외 — 나머지는 전부 블랙박스)
    return import('node:fs').then(async ({ promises: fs }) => {
      for (const file of ['src/app/search/SearchForm.tsx', 'src/app/search/SearchPresets.tsx']) {
        const src = await fs.readFile(file, 'utf8')
        const code = src
          .split('\n')
          .filter((line) => !line.trim().startsWith('//'))
          .join('\n')
        assert.ok(
          !/router\.push\((`|')\/search/.test(code),
          `${file}에 /search 하드코딩 push가 남아있습니다`
        )
        assert.ok(code.includes('usePathname'), `${file}이 usePathname을 쓰지 않습니다`)
      }
    })
  })

})

describe('정렬이 실제 결과 순서를 바꾼다 (Sprint 49) — 소스 계약', () => {
  test('정렬을 바꾸면 페이지 번호가 1로 초기화된다', async () => {
    // router.push는 클라이언트 런타임 동작이라 HTTP로 볼 수 없다. 회귀의 근원인
    // "page를 그대로 둔다"가 소스에 되살아나지 않았는지 정적으로 고정한다.
    // (3페이지에서 "감정가 ↓"를 누르면 감정가가 가장 높은 물건이 아니라 가장 낮은
    //  물건 1건이 보이던 결함 — Sprint 49에서 실제 브라우저로 재현·수정)
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile('src/app/search/SortBar.tsx', 'utf8')
    const code = src.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')
    assert.ok(
      /params\.set\(\s*'page'\s*,\s*'1'\s*\)/.test(code),
      'SortBar가 정렬 변경 시 page를 1로 초기화하지 않습니다'
    )
    assert.ok(
      /searchParams\.get\('sort_order'\)\s*\|\|\s*'desc'/.test(code),
      "SortBar의 sort_order 기본값이 백엔드 기본값('desc')과 다릅니다"
    )
  })

})

describe('기술부채 정리 (Sprint 52) — 소스 계약', () => {
  test('UI 정렬 버튼이 백엔드 화이트리스트를 전부 덮는다', async () => {
    // 어느 한쪽만 늘어나 "타입엔 있는데 UI엔 없는" 상태가 다시 생기지 않도록 고정한다.
    const { promises: fs } = await import('node:fs')
    const types = await fs.readFile('src/app/search/types.ts', 'utf8')
    const union = types.match(/sort_by\?:\s*([^\n]+)/)
    assert.ok(union, 'types.ts에서 sort_by 유니온을 찾지 못했습니다')
    const declared = [...union[1].matchAll(/'([a-z_]+)'/g)].map((m) => m[1])
    const bar = await fs.readFile('src/app/search/SortBar.tsx', 'utf8')
    const exposed = [...bar.matchAll(/value:\s*'([a-z_]+)'/g)].map((m) => m[1])
    const missing = declared.filter((d) => !exposed.includes(d))
    assert.deepEqual(missing, [], `타입에는 있는데 UI에 없는 정렬: ${missing.join(', ')}`)
  })

  test('비로그인 검색조건 저장 시 입력하던 이름이 복귀 URL에 실린다', async () => {
    // 검색조건(쿼리스트링)은 이미 보존됐지만 **입력하던 이름은 사라져** 다시 타이핑해야 했다.
    // 클라이언트 런타임 동작이라 HTTP로 볼 수 없어 소스로 고정한다.
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile('src/app/search/SearchPresets.tsx', 'utf8')
    const code = src.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')
    assert.ok(
      /redirectToLogin\(\s*trimmedName\s*\)/.test(code),
      '로그인 유도 시 입력하던 이름을 넘기지 않습니다'
    )
    assert.ok(
      /useState\(\(\)\s*=>\s*searchParams\.get\('preset_name'\)/.test(code),
      '복귀 후 이름을 URL에서 되살리지 않습니다'
    )
    // 이름이 검색조건이나 저장되는 conditions로 새어 들어가면 안 된다.
    const form = await fs.readFile('src/app/search/SearchForm.tsx', 'utf8')
    assert.ok(
      !form.includes("'preset_name'"),
      'preset_name이 검색조건 키 목록에 섞였습니다'
    )
  })

})

describe('서버 인증 게이트의 위치와 규약 (Sprint 50) — 소스 계약', () => {
  test('서버 게이트는 src/proxy.ts 하나뿐이다', async () => {
    const { promises: fs } = await import('node:fs')
    const exists = async (p) => fs.access(p).then(() => true, () => false)
    assert.ok(await exists('src/proxy.ts'), 'src/proxy.ts가 없습니다 — 서버 인증 게이트가 사라졌습니다')
    assert.ok(
      !(await exists('src/middleware.ts')),
      'src/middleware.ts와 src/proxy.ts가 동시에 존재합니다 — Next.js가 빌드를 실패시킵니다'
    )
  })

  test('proxy.ts가 Next 규약(export 이름 + matcher)을 지킨다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile('src/proxy.ts', 'utf8')
    const code = src.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')
    // proxy 파일에서는 Next 엔트리 템플릿이 `mod.proxy`(없으면 default)를 찾는다.
    assert.ok(
      /export\s+async\s+function\s+proxy\s*\(/.test(code) || /export\s+default\s+/.test(code),
      "proxy.ts가 `proxy` 이름의 함수도 default도 export하지 않습니다"
    )
    assert.ok(/export const config\s*=\s*\{[\s\S]*matcher/.test(code), 'matcher 설정이 없습니다')
  })

  test('보호 경로 목록과 redirect 계약이 그대로다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile('src/proxy.ts', 'utf8')
    const code = src.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')
    // 보호 경로는 **정확히 고정**한다 — 빠지면 개인화 화면이 열리고, 늘어나면 공개 화면이 막힌다.
    // (2026-08-11 Sprint 54에 /mypage 추가. 이 검사가 그 변경을 정확히 잡아냈다.)
    const PROTECTED = ['/properties', '/favorites', '/mypage']
    const m = code.match(/PROTECTED_PREFIXES\s*=\s*\[([^\]]*)\]/)
    assert.ok(m, 'PROTECTED_PREFIXES를 찾지 못했습니다')
    const actual = [...m[1].matchAll(/'([^']+)'/g)].map((x) => x[1])
    assert.deepEqual(actual, PROTECTED, '보호 경로 목록이 바뀌었습니다')
    // Sprint 44 #25의 회귀 방지 지점 — pathname만 넘기면 목록 컨텍스트가 사라진다.
    assert.ok(
      /request\.nextUrl\.pathname\s*\+\s*request\.nextUrl\.search/.test(code),
      'redirect 값이 pathname + search 전체를 보존하지 않습니다'
    )
    assert.ok(/supabase\.auth\.getUser\(\)/.test(code), '서버측 세션 검증(getUser)이 사라졌습니다')
  })

})

describe('레거시 라우트 정리 (Sprint 51) — 소스 계약', () => {
  test('도달 불가 중복 코드 `src/login/`이 제거됐다', async () => {
    const { promises: fs } = await import('node:fs')
    const exists = await fs.access('src/login').then(() => true, () => false)
    assert.ok(
      !exists,
      'src/login/이 되살아났습니다 — src/app/ 밖이라 라우팅되지 않는 중복 코드이며, ' +
        '로그인 후 레거시 /properties로 보내는 확정 정책 위반 구현입니다'
    )
  })

})

describe('로그인 성공 후 복귀 계약 (MASTER_SPEC §3.4) — 소스 계약', () => {
  test('loginAction이 sanitize된 redirect 값으로 복귀시킨다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile('src/app/login/actions.ts', 'utf8')
    const code = src.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')
    assert.ok(
      /redirect\(\s*sanitizeRedirectPath\(\s*formData\.get\('redirect'\)\s*\)\s*\)/.test(code),
      'loginAction이 redirect 파라미터로 복귀시키지 않습니다'
    )
    assert.ok(
      /const DEFAULT_REDIRECT\s*=\s*'\/'/.test(code),
      "redirect가 없을 때의 기본 복귀 경로가 '/'가 아닙니다"
    )
    // Open Redirect 방어가 제거되지 않았는지도 함께 고정한다.
    assert.ok(
      /!value\.startsWith\('\/'\)\s*\|\|\s*\/\^\\\/\[\\\/\\\\\]\//.test(code) ||
        code.includes("value.startsWith('/')"),
      'sanitizeRedirectPath의 내부 상대경로 검사가 사라졌습니다'
    )
  })

  // ★ 소비자(loginAction)만 고정돼 있고 **생산자(로그인 폼)가 비어 있던 자리**
  //   (2026-08-13 Sprint 98 신설).
  //
  //   위 검사는 `loginAction`이 `formData.get('redirect')`를 읽는다는 것만 고정한다.
  //   그런데 로그인 **화면**이 그 값을 폼에 싣지 않으면 `formData.get('redirect')`는
  //   조용히 null이 되고, `sanitizeRedirectPath(null)`이 기본값 '/'을 돌려주므로
  //   **오류 없이 첫 화면으로 보내진다.** 사용자는 보던 물건으로 돌아오지 못하는데
  //   어디에도 실패가 남지 않는다 — MASTER_SPEC §3.4가 막으려던 바로 그 회귀다.
  //
  //   `frontend-contract.test.mjs`에 이 검사가 있었지만 **원리상 통과할 수 없었다**:
  //   `/login`은 `'use client'` + `<Suspense fallback={null}>`이라 서버가 내려주는 HTML은
  //   빈 껍데기이고, hidden input은 하이드레이션 이후에야 생긴다. HTTP로 받은 HTML을
  //   정규식으로 훑는 방식으로는 볼 수 없는 값이다(그 검사는 서버를 띄우고 돌린 적이
  //   없어 실패가 드러나지 않고 있었다).
  //
  //   실제 브라우저에서 하이드레이션 후를 확인한 결과 **제품은 정상**이다 —
  //   `input[name=redirect]`가 type=hidden으로 존재하고 값이 원래 URL과 정확히 일치했다.
  //   즉 고칠 대상은 제품이 아니라 검사 방법이었다. 관측 가능한 곳(소스)으로 옮긴다.
  test('로그인 화면이 redirect 값을 폼에 hidden input으로 싣는다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile('src/app/login/page.tsx', 'utf8')
    const code = src.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')

    // 1) URL의 ?redirect=를 읽는다
    assert.ok(
      /useSearchParams\(\)/.test(code) && /searchParams\.get\('redirect'\)/.test(code),
      '로그인 화면이 URL의 redirect 파라미터를 읽지 않습니다'
    )
    // 2) 읽은 값을 **폼 안에** name="redirect"로 싣는다.
    //    loginAction이 formData.get('redirect')로 꺼내므로 이름이 정확히 일치해야 한다.
    assert.ok(
      /<input[^>]*type="hidden"[^>]*name="redirect"[^>]*value=\{redirectParam\}/.test(code),
      'redirect 값을 hidden input(name="redirect")으로 폼에 싣지 않습니다'
    )
    // 3) 그 input이 실제 제출되는 <form> 안에 있어야 한다 — 폼 밖이면 formData에 실리지 않는다.
    const formStart = code.indexOf('<form')
    const formEnd = code.indexOf('</form>')
    assert.ok(formStart !== -1 && formEnd > formStart, '로그인 <form>을 찾지 못했습니다')
    assert.ok(
      code.slice(formStart, formEnd).includes('name="redirect"'),
      'redirect hidden input이 <form> 바깥에 있어 제출되지 않습니다'
    )
  })

  test('로그아웃 후에는 첫 화면(검색)으로 보낸다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile('src/app/properties/LogoutButton.tsx', 'utf8')
    const code = src.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')
    assert.ok(/signOut\(\)/.test(code), '로그아웃이 세션을 파기하지 않습니다')
    assert.ok(/router\.push\('\/'\)/.test(code), "로그아웃 후 복귀 경로가 '/'가 아닙니다")
    // 서버 컴포넌트가 이전 세션 토큰으로 렌더한 결과(is_favorited 등)를 남기지 않아야 한다.
    assert.ok(/router\.refresh\(\)/.test(code), '로그아웃 후 서버 렌더를 갱신하지 않습니다')
  })

})

describe('마이페이지 — 소스 계약 (Sprint 54)', () => {
  test('기존 사용자 API만 조합하고 새 엔드포인트를 만들지 않는다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile('src/app/mypage/page.tsx', 'utf8')
    for (const path of ['/api/v1/subscriptions/me', '/api/v1/payments', '/api/v1/registry-requests']) {
      assert.ok(src.includes(path), `마이페이지가 ${path}를 쓰지 않습니다`)
    }
    // 관심물건/최근 본 물건은 전용 화면이 이미 있으므로 **링크만** 둔다(중복 구현 금지).
    assert.ok(
      !src.includes('/api/v1/favorites') && !src.includes('/api/v1/recent-items'),
      '이미 전용 화면이 있는 목록을 마이페이지가 다시 조회합니다(중복 구현)'
    )
  })

  test('청구 금액은 축약하지 않고 정확한 원 단위로 표시한다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile('src/app/mypage/page.tsx', 'utf8')
    // `formatPrice`는 12,900원을 "1만"으로 만든다(-22%). 구독 카드가 이미
    // `price.toLocaleString() + '원'`으로 정확히 표시하므로, 내역만 축약하면
    // 같은 결제가 화면마다 다른 금액으로 보인다.
    assert.ok(src.includes('formatWon'), '청구 금액에 formatWon을 쓰지 않습니다')
    assert.ok(
      // ★ 2026-08-20 Sprint 226 — 이 정규식은 원래 **제어문자**로 굳어 있었다.
      //   /\bformatPrice\b/ 로 쓰려던 것이 파일에 0x08(백스페이스) 바이트로 들어가
      //   "백스페이스 문자"를 찾게 돼 **영원히 일치하지 않았다** — 즉 이 단언은
      //   `formatPrice` 가 다시 들어와도 **절대 실패하지 않는** 공허한 검사였다.
      !new RegExp(String.raw`\bformatPrice\b`).test(src),
      '마이페이지가 축약 표기(formatPrice)를 씁니다 — 청구 금액이 실제와 어긋납니다'
    )

    // 검사가 공허하지 않다는 것을 같은 자리에서 증명한다 — 합성 입력에서는 반드시 잡혀야 한다.
    const probe = new RegExp(String.raw`\bformatPrice\b`)
    assert.ok(probe.test(`const x = formatPrice(1)`),
      '검사기가 formatPrice 를 못 잡는다 — 이 단언은 공허하다')
    assert.ok(!probe.test(`const x = formatPriceLike(1)`),
      '단어 경계가 동작하지 않는다')
  })

  test('formatWon이 공용으로 한 곳에만 정의된다', async () => {
    const { promises: fs } = await import('node:fs')
    const lib = await fs.readFile('src/lib/format.ts', 'utf8')
    assert.ok(/export function formatWon/.test(lib), 'src/lib/format.ts에 formatWon이 없습니다')
    // 상세 페이지에 있던 지역 사본을 제거했다 — 다시 생기면 표기가 갈린다.
    const detail = await fs.readFile('src/app/properties/[id]/page.tsx', 'utf8')
    assert.ok(
      !/function formatWon/.test(detail),
      '상세 페이지에 formatWon 지역 사본이 되살아났습니다(중복 정의)'
    )
  })

  test('마이페이지는 서버 인증 게이트 대상이다', async () => {
    const { promises: fs } = await import('node:fs')
    const proxy = await fs.readFile('src/proxy.ts', 'utf8')
    assert.ok(
      /PROTECTED_PREFIXES\s*=\s*\[[^\]]*'\/mypage'/.test(proxy),
      'proxy.ts의 보호 경로에 /mypage가 없습니다'
    )
  })

  test('구독 해지 같은 미결정 정책 액션을 임의로 넣지 않았다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile('src/app/mypage/page.tsx', 'utf8')
    // 해지 정책이 미정이고 사용자용 해지 엔드포인트도 없다 — 조회 전용이어야 한다.
    assert.ok(!/method:\s*'(POST|DELETE|PATCH)'/.test(src), '마이페이지에 쓰기 동작이 있습니다')
    assert.ok(!src.includes('postJSON') && !src.includes('deleteJSON'),
      '마이페이지가 쓰기 API를 호출합니다 — 조회 전용 화면입니다')
  })
})

describe('검색 파라미터 계약: 프런트가 보내는 것과 백엔드가 받는 것 (Sprint 55)', () => {
  // 2026-08-11 감사에서 발견: `SearchForm.buildSearchQuery()`가 백엔드에 존재하지 않는
  // 파라미터 5개를 만들고 있었다(면적 4 + 특수조건 1). FastAPI는 모르는 쿼리 파라미터를
  // **조용히 무시**하므로, 값이 실리는 순간 "조건을 걸었는데 전체 결과가 나오는" 상태가 된다.
  //
  // 지금은 해당 UI 입력이 "준비 중입니다" 자리표시자라 값이 실릴 수 없어 무해하다.
  // 문제는 그 사실이 **주석에만** 있다는 것이다 — 누군가 입력을 살리는 순간 아무 경고 없이
  // 잘못된 결과가 나간다. 미지원 목록을 여기 고정해, 늘어나면 실패하고 구현되면 목록에서
  // 빼도록 강제한다.
  const KNOWN_UNSUPPORTED = new Set([
    'min_building_area', 'max_building_area',
    'min_land_area', 'max_land_area',
    'special_conditions',
  ])

  async function read(file) {
    const { promises: fs } = await import('node:fs')
    return fs.readFile(file, 'utf8')
  }

  test('프런트가 만드는 쿼리 키가 백엔드 파라미터를 벗어나지 않는다', async () => {
    const form = await read('src/app/search/SearchForm.tsx')
    const api = await read('api/v1/search.py')

    // 백엔드가 선언한 Query 파라미터 이름
    const backend = new Set()
    for (const m of api.matchAll(/^\s{4}(\w+)\s*:\s*[^=]+=\s*Query\(/gm)) backend.add(m[1])
    assert.ok(backend.size > 10, `백엔드 파라미터 추출 실패 (${backend.size}개)`)

    // 프런트가 query 객체에 넣는 키
    const sent = new Set()
    for (const m of form.matchAll(/\bquery\.(\w+)\s*=/g)) sent.add(m[1])
    assert.ok(sent.size > 10, `프런트 쿼리 키 추출 실패 (${sent.size}개)`)

    const unknown = [...sent].filter((k) => !backend.has(k)).sort()
    const unexpected = unknown.filter((k) => !KNOWN_UNSUPPORTED.has(k))
    assert.deepEqual(
      unexpected, [],
      `백엔드가 모르는 검색 파라미터를 보냅니다(조용히 무시되어 조건 없는 결과가 나옵니다): ${unexpected.join(', ')}`
    )
  })

  test('미지원 목록에 올려둔 것이 실제로 아직 미지원이다', async () => {
    // 구현됐는데 목록에 남아 있으면, 그 파라미터가 다시 깨져도 위 검사가 눈감아 준다.
    const api = await read('api/v1/search.py')
    const backend = new Set()
    for (const m of api.matchAll(/^\s{4}(\w+)\s*:\s*[^=]+=\s*Query\(/gm)) backend.add(m[1])

    const nowSupported = [...KNOWN_UNSUPPORTED].filter((k) => backend.has(k)).sort()
    assert.deepEqual(
      nowSupported, [],
      `백엔드가 이미 지원하는데 미지원 목록에 남아 있습니다 — 목록에서 빼십시오: ${nowSupported.join(', ')}`
    )
  })

  // 2026-08-14 신설. 위 두 검사는 **프런트 ↔ 백엔드**를 본다.
  // 빠져 있던 것은 **프런트 안쪽의 두 목록**이다.
  //
  //     buildSearchQuery()   URL 에 실어 보낼 파라미터를 만든다
  //     FILTER_PARAM_KEYS    "검색조건 저장"이 URL 에서 뽑아 저장할 키 목록
  //
  // 둘이 어긋나면 조용히 틀린다. 새 필터를 `buildSearchQuery()` 에만 추가하면
  // 검색은 정상 동작하는데 **저장된 검색조건에서는 그 필터가 빠진다.**
  // 사용자는 저장한 조건을 다시 불러왔을 때 **다른 결과**를 보게 되고,
  // 오류도 빈 화면도 아니라 알아챌 방법이 없다.
  //
  // 반대 방향도 막는다 — `FILTER_PARAM_KEYS` 에만 남은 키는 죽은 항목이고,
  // 그것이 쌓이면 목록이 실제 필터 집합을 더 이상 설명하지 못한다.
  //
  // 두 목록은 같은 파일(`SearchForm.tsx`)에 있지만 **따로 관리된다** —
  // `SearchPresets.tsx` 가 import 해 쓰는 쪽은 `FILTER_PARAM_KEYS` 뿐이다.
  // 2026-08-14 실측: 양쪽 24개, 차이 0.
  test('저장되는 검색조건 키가 실제로 보내는 파라미터와 같다', async () => {
    const form = await read('src/app/search/SearchForm.tsx')

    const listMatch = form.match(/FILTER_PARAM_KEYS\s*=\s*\[([\s\S]*?)\]\s*as const/)
    assert.ok(listMatch, 'FILTER_PARAM_KEYS 선언을 찾지 못했습니다')
    const saved = new Set([...listMatch[1].matchAll(/'([a-z_]+)'/g)].map((m) => m[1]))

    const body = form.slice(form.indexOf('function buildSearchQuery'))
    const build = body.slice(0, body.indexOf('function handleSearch'))
    const sent = new Set([...build.matchAll(/\bquery\.([a-z_]+)\s*=/g)].map((m) => m[1]))

    // 추출이 실패하면 두 집합이 비어 "차이 없음"으로 통과한다 — 공허한 검사 방지.
    assert.ok(saved.size > 10, `FILTER_PARAM_KEYS 추출 실패 (${saved.size}개)`)
    assert.ok(sent.size > 10, `buildSearchQuery 키 추출 실패 (${sent.size}개)`)

    const lost = [...sent].filter((k) => !saved.has(k)).sort()
    assert.deepEqual(
      lost, [],
      `보내지만 저장되지 않는 검색 파라미터입니다 — 저장한 조건을 다시 불러오면 이 필터가 빠집니다: ${lost.join(', ')}`
    )
    const dead = [...saved].filter((k) => !sent.has(k)).sort()
    assert.deepEqual(
      dead, [],
      `FILTER_PARAM_KEYS 에만 남아 있는 키입니다(더 이상 보내지 않음) — 목록에서 빼십시오: ${dead.join(', ')}`
    )
  })

  test('미지원 파라미터는 TODO로 표시돼 있다', async () => {
    const form = await read('src/app/search/SearchForm.tsx')
    const lines = form.split('\n')
    for (const key of KNOWN_UNSUPPORTED) {
      const idx = lines.findIndex((l) => l.includes(`query.${key} =`))
      if (idx === -1) continue // 프런트가 더 이상 보내지 않으면 통과

      // 하나의 TODO 주석이 연속된 여러 대입을 함께 덮는다(면적 4줄이 한 블록).
      // 그래서 고정 폭으로 뒤를 보면 블록 끝 줄에서 놓친다 — 주석을 만날 때까지 거슬러 올라간다.
      let marked = false
      for (let i = idx; i >= 0; i--) {
        const l = lines[i].trim()
        if (l.startsWith('//')) {
          marked = /TODO\(API 미지원\)/.test(l)
          break
        }
        // 대입은 `if (form.x) query.y = ...` 형태라 줄 시작이 `query.`가 아니다 — 포함 여부로 본다.
        if (i !== idx && !l.includes('query.') && l !== '') break
      }
      assert.ok(
        marked,
        `query.${key}가 미지원인데 바로 앞 주석에 TODO(API 미지원) 표시가 없습니다 (line ${idx + 1})`
      )
    }
  })
})

describe('응답 보안 헤더 (Sprint 127) — 소스 계약', () => {
  // `next.config.ts`는 TypeScript라 이 Node 테스트 러너(.mjs, 트랜스파일러 없음)가
  // 직접 import할 수 없다 — 이 파일의 기존 관례대로 텍스트로 읽어 정적으로 대조한다.
  //
  // 이 검사가 지키려는 것은 "값이 옳은가"가 아니라(그건 브라우저/curl로만 확인 가능,
  // docs/SPRINT127_SECURITY_HEADERS_APPLIED.md 참고) **누군가 이 블록을 지우거나
  // `X-Frame-Options`를 실수로 백엔드처럼 넣지 않는가**다 — 백엔드(`api_server.py`)는
  // 반대로 `X-Frame-Options`를 **의도적으로 뺀 것**과 짝을 이루므로(이 백엔드 자체가
  // 문서 뷰어 iframe의 대상), 두 파일이 서로 다른 이유로 서로 다른 값을 가져야
  // 한다는 사실 자체가 실수로 합쳐지기 쉬운 지점이다.
  async function read(file) {
    const { promises: fs } = await import('node:fs')
    return fs.readFile(file, 'utf8')
  }

  test('next.config.ts가 poweredByHeader를 끈다', async () => {
    const src = await read('next.config.ts')
    assert.ok(
      /poweredByHeader\s*:\s*false/.test(src),
      'poweredByHeader: false가 없습니다 — X-Powered-By: Next.js가 다시 노출됩니다'
    )
  })

  test('next.config.ts의 headers()가 정책 결정 불필요한 4개를 전부 선언한다', async () => {
    const src = await read('next.config.ts')
    const expected = [
      ['X-Content-Type-Options', 'nosniff'],
      ['X-Frame-Options', 'DENY'],
      ['Referrer-Policy', 'strict-origin-when-cross-origin'],
      ['Permissions-Policy', 'camera=(), microphone=(), geolocation=()'],
    ]
    for (const [key, value] of expected) {
      const re = new RegExp(
        `key:\\s*["']${key}["']\\s*,\\s*value:\\s*["']${value.replace(/[()]/g, '\\$&')}["']`
      )
      assert.ok(re.test(src), `next.config.ts에 ${key}: ${value} 헤더가 없습니다`)
    }
  })

  test('api_server.py는 X-Frame-Options를 넣지 않는다(이 백엔드가 iframe 대상이라 의도적)', async () => {
    const src = await read('api_server.py')
    // "언급"이 아니라 "실제로 헤더를 설정하는 코드"만 본다 — 이유를 설명하는 주석
    // 자체에 "X-Frame-Options" 문자열이 들어 있으므로(바로 위 문단), 주석까지 걸리는
    // 순진한 문자열 검색은 이 파일이 스스로를 위반으로 잡는 자기모순에 빠진다. 실제
    // 설정 코드의 모양(`response.headers["X-Frame-Options"] = ...` 또는
    // `headers["X-Frame-Options"] =`)만 규칙 위반으로 본다.
    assert.ok(
      !/headers\s*\[\s*["']X-Frame-Options["']\s*\]\s*=/i.test(src),
      'api_server.py가 실제로 X-Frame-Options 헤더를 설정하고 있습니다 — 이 백엔드는 문서 뷰어 iframe의 대상이라 넣으면 깨집니다(docs/SPRINT127_SECURITY_HEADERS_APPLIED.md §3 참고)'
    )
    assert.ok(
      /X-Content-Type-Options.*nosniff/s.test(src),
      'api_server.py에 X-Content-Type-Options: nosniff가 없습니다'
    )
  })
})
