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
import { KNOWN_UNSUPPORTED } from './_search_param_contract.mjs'

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
  // 2026-08-26: 면적 4종(min/max_building_area, min/max_land_area)을 **구현했다** —
  //   migration 025 가 컬럼을, normalizer.extract_areas() 가 추출을,
  //   api/v1/search.py 가 WHERE 절을 맡는다.
  //   그래서 목록에서 뺐다. 남은 것은 special_conditions 하나다.
  //
  // ★ 목록 자체는 `tests/_search_param_contract.mjs` **한 곳**에만 둔다.
  //   같은 목록이 이 파일과 frontend-contract.test.mjs 에 두 벌 생겼다가, 한쪽에서만
  //   빼면 다른 쪽이 계속 눈감아 주는 구조가 됐다(BUGS #204 가 경계하는 그것).

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

describe('좁은 폭 가로 넘침 (Sprint 240) — 소스 계약', () => {
  // ────────────────────────────────────────────────────────────────
  // 2026-08-21 Sprint 240. **실제 320px 창**에서 처음으로 재현했다.
  //
  // 그동안 이 저장소는 뷰포트를 줄이지 못해(Sprint 219/223/224/231) 좁은 폭을
  // 간접적으로만 쟀다. 이번에 `window.open(..., 'width=320')` 으로 진짜 320px
  // 창을 띄우니 미디어쿼리까지 정상 평가됐고(`matchMedia('(min-width: 768px)')`
  // = false), 그 창에서 두 곳이 실제로 넘쳤다:
  //
  //   /search        검색조건 저장의 저장 버튼   오른쪽 끝 295px vs 뷰포트 289px
  //   전 화면(헤더)   로그인 상태의 우측 메뉴 묶음  오른쪽 끝 308px vs 뷰포트 289px
  //
  // 둘 다 `documentElement.scrollWidth > clientWidth` 를 만들어 **페이지 전체가
  // 가로로 스크롤**됐다. 헤더는 전 화면 공용이라 파급이 컸고, 비로그인일 때는
  // 메뉴가 짧아 들어가서 — 로그아웃 상태로만 보면 멀쩡해 보였다.
  //
  // 여기서 소스로 고정하는 이유: CI/테스트 러너에는 브라우저가 없어 실제 렌더를
  // 다시 잴 수 없다. 그래서 **고침을 되돌리는 편집**을 잡는 것으로 대신한다.
  // (실제 렌더 재측정 결과는 docs/SPRINT240_*.md 에 수치로 남겼다.)
  // ────────────────────────────────────────────────────────────────
  async function read(file) {
    const { promises: fs } = await import('node:fs')
    return fs.readFile(file, 'utf8')
  }
  /** 주석을 걷어낸 "실제 코드"만 본다 — 이유를 적은 주석이 스스로를 통과시키면 안 된다. */
  function codeOnly(src) {
    return src
      .split('\n')
      .filter((l) => {
        const t = l.trim()
        return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*')
      })
      .join('\n')
  }

  test('검색조건 저장 입력이 min-w-0 을 갖는다 (flex min-width:auto 넘침)', async () => {
    const code = codeOnly(await read('src/app/search/SearchPresets.tsx'))
    const m = code.match(/const inputClass\s*=\s*\n?\s*'([^']*)'/)
    assert.ok(m, 'SearchPresets.tsx 에서 inputClass 를 찾지 못했습니다(검사가 공허해졌습니다)')
    const cls = m[1]
    assert.ok(cls.includes('flex-1'), `inputClass 가 flex-1 이 아닙니다: ${cls}`)
    assert.ok(
      cls.includes('min-w-0'),
      'SearchPresets 의 입력에 min-w-0 이 없습니다 — flex 항목은 min-width 기본값이 auto 라 ' +
        'input 의 고유 폭 아래로 줄지 않고, 320px 에서 옆의 저장 버튼과 함께 줄을 넘깁니다 ' +
        '(실측: 저장 버튼 오른쪽 끝 295px vs 뷰포트 289px).'
    )
  })

  test('공통 헤더가 좁은 폭에서 접힐 수 있다 (flex-wrap + 우측 묶음이 shrink-0 이 아니다)', async () => {
    const code = codeOnly(await read('src/components/SiteHeader.tsx'))

    // (1) 바깥 줄이 접힐 수 있어야 한다
    const rowMatch = code.match(/\$\{CONTAINER\}\s+py-4\s+([^`]*)`/)
    assert.ok(rowMatch, 'SiteHeader 의 헤더 줄 className 을 찾지 못했습니다(검사가 공허해졌습니다)')
    assert.ok(
      rowMatch[1].includes('flex-wrap'),
      `헤더 줄에 flex-wrap 이 없습니다 — 320px 로그인 상태에서 페이지 전체가 가로 스크롤됩니다: ${rowMatch[1]}`
    )

    // (2) 우측 메뉴 묶음이 shrink-0 으로 버티면 안 된다
    const rightMatch = code.match(/className="flex[^"]*justify-end[^"]*"/)
    assert.ok(
      rightMatch,
      'SiteHeader 의 우측 묶음(justify-end) 을 찾지 못했습니다(검사가 공허해졌습니다)'
    )
    const right = rightMatch[0]
    assert.ok(
      !/\bshrink-0\b/.test(right),
      `헤더 우측 묶음이 shrink-0 입니다 — 줄어들지 못해 CONTAINER 밖으로 밀려납니다: ${right}`
    )
    assert.ok(
      /\bflex-wrap\b/.test(right) && /\bmin-w-0\b/.test(right),
      `헤더 우측 묶음에 flex-wrap 과 min-w-0 이 둘 다 있어야 합니다: ${right}`
    )
  })

  // -------------------------------------------------------------------------
  // 큰 글씨(루트 글꼴 200%)에서 버튼 줄이 부모를 넘지 않는가 — 2026-08-21 Sprint 247
  //
  // ## 왜 생겼나 — 접근성 검사가 소스만 세고 있었다
  //
  // `test_frontend_accessibility.py` 는 1,143줄이지만 `text-xs` 가 몇 개인지 같은
  // **문자열만 센다.** "rem 을 쓰니 루트 글꼴을 키우면 따라 커진다"는 가정은 적혀
  // 있었지만, 키웠을 때 레이아웃이 견디는지는 **한 번도 렌더링해서 재지 않았다.**
  //
  // 실제 브라우저로 320/360/390/430 × 글꼴 100/150/200% = 36칸을 재니 2칸이 깨졌다:
  //
  //     /        320px 글꼴 200%  ->  DIV.py-4 flex gap-2 > BUTTON.flex-1  (+8px, 부모 175)
  //     /search  320px 글꼴 200%  ->  DIV.flex gap-2 > BUTTON.shrink-0     (+7px, 부모 175)
  //
  // 원인은 이 저장소가 이미 여러 번 밟은 flex `min-width:auto` 다. `shrink-0` 버튼이
  // 글꼴을 따라 커지는데 옆의 형제는 자기 콘텐츠 폭 아래로 줄지 못해 부모를 넘긴다.
  //
  // ## 왜 flex-wrap 인가 (min-w-0 이 아니라)
  //
  // 둘 다 넘침은 없앤다(브라우저에서 실측). 그런데 `min-w-0`/`shrink-0` 제거 쪽은
  // 버튼이 찌그러져 **라벨이 잘린다**. WCAG 1.4.4 는 200% 확대에서 "내용 손실 없음"을
  // 요구하므로, 줄을 바꿔 글자를 온전히 보여 주는 `flex-wrap` 이 맞다.
  // 보통 크기에서는 두 버튼이 한 줄에 들어가 화면이 달라지지 않는다.
  //
  // 이 검사는 그 두 줄이 접힐 수 있는 상태로 남아 있는지 고정한다.
  // -------------------------------------------------------------------------
  test('큰 글씨에서 검색 버튼 줄이 접힐 수 있다 (SearchForm)', async () => {
    const code = codeOnly(await read('src/app/search/SearchForm.tsx'))
    const row = code.match(/<div className="py-4 flex([^"]*)"/)
    assert.ok(
      row,
      'SearchForm 의 버튼 줄(py-4 flex ...) 을 찾지 못했습니다(검사가 공허해졌습니다)'
    )
    assert.ok(
      /\bflex-wrap\b/.test(row[1]),
      '검색/초기화 버튼 줄에 flex-wrap 이 없습니다 — 루트 글꼴 200% + 320px 에서 ' +
        'shrink-0 인 "초기화" 가 커지며 "검색"(flex-1, min-width:auto)을 밀어 ' +
        `부모 175px 를 8px 넘깁니다: ${row[1]}`
    )
  })

  test('큰 글씨에서 검색조건 저장 줄이 접힐 수 있다 (SearchPresets)', async () => {
    const code = codeOnly(await read('src/app/search/SearchPresets.tsx'))
    // 저장 버튼을 품은 줄을 찾는다
    const row = code.match(/<div className="flex([^"]*)">\s*<input/)
    assert.ok(
      row,
      'SearchPresets 의 입력+저장 줄을 찾지 못했습니다(검사가 공허해졌습니다)'
    )
    assert.ok(
      /\bflex-wrap\b/.test(row[1]),
      '검색조건 저장 줄에 flex-wrap 이 없습니다 — 입력칸이 이미 min-w-0 인데도 ' +
        'shrink-0 인 "저장" 버튼 자체가 글꼴 200% 에서 116px 까지 커져 ' +
        `부모 175px 를 7px 넘깁니다: ${row[1]}`
    )
  })

  test('주요 메뉴(PrimaryNav)가 접힐 수 있다', async () => {
    const code = codeOnly(await read('src/components/PrimaryNav.tsx'))
    const nav = code.match(/<nav[^>]*className="([^"]*)"/)
    assert.ok(nav, 'PrimaryNav 의 nav className 을 찾지 못했습니다(검사가 공허해졌습니다)')
    assert.ok(
      nav[1].includes('flex-wrap'),
      `PrimaryNav 에 flex-wrap 이 없습니다 — 메뉴 4개가 한 줄에 안 들어가면 화면을 밀어냅니다: ${nav[1]}`
    )
    // 접근성 랜드마크는 그대로여야 한다(이 고침이 다른 것을 망가뜨리지 않았는지)
    assert.ok(/aria-label="주요 메뉴"/.test(code), 'PrimaryNav 의 nav 랜드마크 이름이 사라졌습니다')
  })
})

describe('목록 카드가 grid 트랙을 밀어내지 않는다 (Sprint 240) — 소스 계약', () => {
  // ────────────────────────────────────────────────────────────────
  // 2026-08-21 실측(실제 320px 창). 세 목록 화면이 **같은 카드 구조**를 쓰는데,
  // grid 항목인 `<Link className="block">` 의 `min-width` 가 기본값 `auto` 였다.
  //
  //   grid 트랙은 항목의 min-content 아래로 줄지 않는다. 카드 안에는 `truncate`
  //   (= white-space:nowrap) 문단이 있어 그 min-content 가 **문자열 전체 폭**이다.
  //   -> 컨테이너는 257px 인데 트랙이 그보다 넓어져 페이지가 가로로 스크롤됐다.
  //
  //   /search             컨테이너 257px vs 트랙 277.6px (카드 오른쪽 끝 294 vs 289)
  //   /favorites          컨테이너 257px vs 트랙 727.7px (카드 오른쪽 끝 744 vs 289)
  //   /properties/recent  같은 구조 — 같은 결함
  //
  // `min-w-0` 을 준 뒤 세 화면 모두 트랙 257px, 넘침 0, 가로 스크롤 없음으로
  // 재측정됐고, 900px/1400px 에서 2열/3열이 그대로 나오는 것도 확인했다.
  //
  // ★ 이 검사가 잡는 것은 "min-w-0 을 지우는 편집"이다. 실제 렌더 재측정은
  //   브라우저가 필요해 CI 에서 못 한다(수치는 docs/SPRINT240_*.md 에 남겼다).
  // ────────────────────────────────────────────────────────────────
  const LIST_FILES = [
    'src/app/search/ResultList.tsx',
    'src/app/favorites/page.tsx',
    'src/app/properties/recent/page.tsx',
  ]

  async function read(file) {
    const { promises: fs } = await import('node:fs')
    return fs.readFile(file, 'utf8')
  }
  function codeOnly(src) {
    return src
      .split('\n')
      .filter((l) => {
        const t = l.trim()
        return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*')
      })
      .join('\n')
  }

  for (const file of LIST_FILES) {
    test(`${file} 의 카드 Link 가 min-w-0 을 갖는다`, async () => {
      const code = codeOnly(await read(file))

      // 먼저 이 파일이 실제로 반응형 grid 를 쓰는지 확인한다 —
      // 구조가 바뀌었는데 검사만 남아 조용히 통과하는 것을 막는다.
      assert.ok(
        /grid[^"'`]*md:grid-cols-2/.test(code),
        `${file} 에서 반응형 grid(md:grid-cols-2) 를 찾지 못했습니다 — 검사가 공허해졌습니다`
      )

      const links = code.match(/<Link[^>]*className="block[^"]*"/g)
      assert.ok(
        links && links.length > 0,
        `${file} 에서 카드 Link(className="block...") 를 찾지 못했습니다 — 검사가 공허해졌습니다`
      )
      for (const l of links) {
        assert.ok(
          /className="block[^"]*\bmin-w-0\b/.test(l),
          `${file} 의 카드 Link 에 min-w-0 이 없습니다 — grid 항목의 min-width 기본값 auto ` +
            `때문에 좁은 화면에서 트랙이 카드 min-content 만큼 벌어져 페이지가 가로로 ` +
            `스크롤됩니다(실측 320px): ${l}`
        )
      }
    })
  }
})

describe('물건종류 배지가 세로로 쪼개지지 않는다 (Sprint 242) — 소스 계약', () => {
  // ────────────────────────────────────────────────────────────────
  // 2026-08-21, `audit_viewport.py` 가 **실제 320px 뷰포트**에서 처음 잡았다.
  //
  //   카드의 [물건종류 배지] / [D-day + 하트] 줄은 justify-between 인데
  //   오른쪽 묶음이 shrink-0 이라 줄어들지 않는다. 그래서 폭이 모자라면
  //   **왼쪽 배지만** 계속 짜부라진다.
  //
  //     320px  가용 147px = 배지 37px + gap 8 + 오른쪽 110px(고정)
  //            "연립주택,다세대,빌라" 가 37px 안에서 **9줄**로 접힌다
  //            -> 한 글자씩 세로로 늘어선 기둥, 카드 높이 403px
  //     360px  3줄 / 390px 2줄 / 430px 2줄
  //
  //   페이지가 가로로 스크롤되지는 않아서 "가로 넘침만" 보던 검사들은 전부 놓쳤다.
  //   `flex-wrap` 을 준 뒤 전 폭에서 **1줄**(144px)로 회복됐다.
  //
  // 여기서 소스로 잠그는 이유: 실제 렌더 재측정은 브라우저가 필요해 CI 에서 못 한다.
  // (재현 도구는 저장소에 있다 — `python audit_viewport.py`)
  // ────────────────────────────────────────────────────────────────
  const CARD_FILES = [
    'src/app/search/ResultList.tsx',
    'src/app/favorites/page.tsx',
    'src/app/properties/recent/page.tsx',
  ]

  async function read(file) {
    const { promises: fs } = await import('node:fs')
    return fs.readFile(file, 'utf8')
  }
  function codeOnly(src) {
    return src.split('\n').filter((l) => {
      const t = l.trim()
      return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*') && !t.startsWith('{/*')
    }).join('\n')
  }

  for (const file of CARD_FILES) {
    test(`${file} 의 배지 줄이 접힐 수 있다`, async () => {
      const code = codeOnly(await read(file))
      const rows = code.match(/className="[^"]*items-start justify-between[^"]*"/g)
      assert.ok(
        rows && rows.length > 0,
        `${file} 에서 배지 줄(items-start justify-between)을 찾지 못했습니다 — 검사가 공허해졌습니다`
      )
      for (const r of rows) {
        assert.ok(
          /\bflex-wrap\b/.test(r),
          `${file} 의 배지 줄에 flex-wrap 이 없습니다 — 좁은 화면에서 물건종류 배지가 ` +
            `세로 한 글자씩 쪼개집니다(실측 320px: 9줄, 카드 높이 403px): ${r}`
        )
      }
    })
  }

  test('재현 도구가 저장소에 있다(주석만 남고 도구가 사라지지 않도록)', async () => {
    const src = await read('audit_viewport.py')
    assert.ok(/Emulation\.setDeviceMetricsOverride/.test(src),
      'audit_viewport.py 가 진짜 뷰포트를 만들지 않습니다')
    assert.ok(/parentOverflow/.test(src),
      'audit_viewport.py 에 부모 넘침 탐지가 없습니다 — 이 결함을 잡은 검사입니다')
    assert.ok(!/--hide-scrollbars/.test(src.replace(/#[^\n]*/g, '')),
      'audit_viewport.py 가 스크롤바를 숨깁니다 — 가용 폭이 넓어져 결함이 안 보입니다')
  })
})

describe('사진 상태를 화면이 구분해서 말한다 (Sprint 243) — 소스 계약', () => {
  // ────────────────────────────────────────────────────────────────
  // 사진 상태는 네 가지이고, 사용자가 **할 일이 서로 다르다**:
  //
  //     READY       볼 사진이 있다
  //     NO_IMAGE    법원이 사진을 안 준다        -> 기다려도 안 생긴다
  //     FAILED      재시도가 소진된 진짜 실패     -> 다음 수집에서 다시 시도된다
  //     COLLECTING  아직 수집 전                 -> 기다리면 된다
  //
  // API 쪽 판정(`api/v1/item.py:_images_status`)은 mutation 3종으로 잠겨 있다
  // (test_asset_pipeline.py). 그런데 **화면이 그 구분을 그리는지는 아무도 보지 않았다.**
  //
  // 2026-08-21 실측: 상세페이지의 `FAILED` 분기를 `false` 로 죽였더니
  //   tsc 0 / node 전 검사 통과 / frontend_accessibility 통과 / document_status_sync 통과
  // — **아무도 울지 않았다.** 그러면 재시도가 소진된 실패가 "사진 수집 중입니다"로 보인다.
  // 이 저장소의 함정 목록 "이미지 없음과 이미지 실패를 혼동하지 않는다"가 화면에서 깨진다.
  //
  // ★ 문구는 고정하지 않는다(제품 결정이다). **분기의 존재와 상호 구별**만 고정한다.
  //
  // ★ 이 검사를 처음 쓸 때 두 번 틀렸고, 그 경위를 남긴다:
  //     (1) 어휘 출처를 `api/v1/item.py` 로 잡았는데 그 파일에는 NO_IMAGE 가 **주석에만**
  //         있다. API 는 `row["status"]` 를 그대로 흘려보내므로 값의 출처는
  //         `storage/database.py`(DOC_STATUS_HAS_ARTIFACT / doc_worker.py)다.
  //     (2) `new RegExp("...\\s*...")` 를 셸 heredoc 으로 쓰다가 역슬래시가 한 겹
  //         사라져 `s*` 가 됐다. 정규식 대신 **공백을 지운 문자열 포함 검사**로 바꿨다.
  // ────────────────────────────────────────────────────────────────
  const DETAIL = 'src/app/properties/[id]/page.tsx'

  async function read(file) {
    const { promises: fs } = await import('node:fs')
    return fs.readFile(file, 'utf8')
  }
  /** 주석을 걷어내고 공백을 지운다 — 들여쓰기/줄바꿈에 흔들리지 않게. */
  function normalized(src) {
    const code = src.split('\n').filter((l) => {
      const t = l.trim()
      return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*') && !t.startsWith('{/*')
    }).join('\n')
    return code.replace(/\s+/g, '')
  }

  test('사진 상태 어휘가 제품 코드에 실제로 있다(검사가 공허하지 않다)', async () => {
    // 값을 만들어내는 곳들. 여기가 바뀌면 이 검사의 전제가 무너진 것이므로 알려야 한다.
    const dw = await read('doc_worker.py')
    const db = await read('storage/database.py')
    assert.ok(/"NO_IMAGE"/.test(dw), 'doc_worker.py 가 NO_IMAGE 를 만들지 않습니다')
    assert.ok(/"NO_IMAGE"/.test(db), 'storage/database.py 에 NO_IMAGE 어휘가 없습니다')
    const api = await read('api/v1/item.py')
    assert.ok(/_images_status/.test(api), 'api/v1/item.py 에 _images_status 가 없습니다')
  })

  test('상세페이지가 NO_IMAGE 와 FAILED 를 각각 따로 분기한다', async () => {
    const flat = normalized(await read(DETAIL))
    for (const state of ['NO_IMAGE', 'FAILED']) {
      assert.ok(
        flat.includes(`images_status==='${state}'`),
        `${DETAIL} 가 images_status === '${state}' 를 분기하지 않습니다 — ` +
          `그 상태의 사용자가 다른 상태의 안내를 보게 됩니다 ` +
          `(NO_IMAGE=법원이 안 준다 / FAILED=재시도 소진: 사용자가 할 일이 다릅니다)`
      )
    }
  })

  test('두 분기가 서로 다른 **문구**를 말한다(구분한 의미가 있다)', async () => {
    // ★ 조건문을 뺀 **본문 문구**만 비교한다.
    //   처음에는 매치 지점부터 200자를 잘라 비교했는데, 그 조각은 늘
    //   `images_status==='NO_IMAGE'` / `...'FAILED'` 로 **시작이 달라서**
    //   문구를 똑같이 바꿔도 통과했다(2026-08-21 mutation 으로 확인 - 공허한 단언이었다).
    //   그래서 `<p ...> 여기 </p>` 안의 글자만 뽑아 비교한다.
    const flat = normalized(await read(DETAIL))
    const message = (state) => {
      const i = flat.indexOf(`images_status==='${state}'`)
      if (i < 0) return ''
      const seg = flat.slice(i, i + 400)
      const m = seg.match(/>([^<>]{4,})</)          // 첫 텍스트 노드
      return m ? m[1] : ''
    }
    const a = message('NO_IMAGE'), b = message('FAILED')
    assert.ok(a && b, `분기 문구를 읽지 못했습니다(검사가 공허해졌습니다): a=${a} b=${b}`)
    assert.notEqual(
      a, b,
      `NO_IMAGE 와 FAILED 가 같은 문구입니다(${a}) — 구분한 의미가 없습니다. ` +
        `NO_IMAGE 는 "기다려도 안 생긴다", FAILED 는 "다시 시도된다" 여서 안내가 달라야 합니다`
    )
  })
})

describe('상세 화면의 늦은 응답 방어 (BUGS #210) — 소스 계약', () => {
  // 왜 소스로 보는가 —
  //
  //   `/properties/[id]` 는 이전/다음 이동이 **같은 라우트의 파라미터 전환**이라
  //   컴포넌트가 재마운트되지 않는다. 그래서 A 를 요청한 뒤 곧바로 B 로 넘어가면
  //   **A 의 응답이 나중에 도착해 B 화면을 덮을 수 있다.** 화면에는 "다른 물건의
  //   상세"가 그대로 보인다 — 오류도 로딩도 아니라서 사용자는 그게 틀린 줄 모른다.
  //
  //   소스는 그 방어를 이미 갖고 있다: 요청 시작 시 `const requestId = id` 를 잡고
  //   **모든 await 뒤에** `idRef.current !== requestId` 로 끊는다. 그런데 2026-08-25
  //   실측 기준 **그 방어를 참조하는 테스트가 하나도 없었다**
  //   (`grep -rn idRef tests/ test_*.py` -> 0건). 한 줄만 지워도 아무도 모른다.
  //
  //   경합 자체는 node --test 에서 재현하기 어렵다(React 렌더러도 DOM 도 없다).
  //   그래서 `src/proxy.ts` 계약을 소스로 고정한 것과 같은 방식으로 **구조**를 본다.
  const FILE = 'src/app/properties/[id]/page.tsx'
  const GUARD = /idRef\.current\s*(!==|===)\s*requestId/

  // ★ 판정 로직은 **한 벌**이다. 본 검사와 자기 검증이 각자 구현하면 갈라진다
  //   (2026-08-25에 실제로 갈라져 자기 검증만 엉뚱하게 붉어졌다 — BUGS #204 와 같은 계열).
  function unguardedWrites(source) {
    const lines = source.split(/\r?\n/)
    const starts = []
    lines.forEach((l, i) => {
      if (/const\s+requestId\s*=\s*id\b/.test(l)) starts.push(i)
    })
    const hits = []
    for (const start of starts) {
      let sawAwait = false
      let guarded = true
      let depth = 0
      // `requestId` 를 선언한 **그 함수 안에서만** 본다. 중괄호 깊이가 음수가 되면
      // 함수가 끝난 것이다 — 고정 줄 수로 훑으면 뒤따르는 별개 핸들러까지 끌어와
      // 오탐이 난다(requireToken / performRegistryRequest 는 requestId 를 잡지 않는다).
      for (let i = start + 1; i < lines.length; i += 1) {
        const line = lines[i]
        for (const ch of line) {
          if (ch === '{') depth += 1
          else if (ch === '}') depth -= 1
        }
        if (depth < 0) break
        if (line.trim().startsWith('//')) continue
        if (/\bawait\b/.test(line)) { sawAwait = true; guarded = false }
        if (GUARD.test(line)) guarded = true
        if (sawAwait && !guarded && /\bset[A-Z]\w*\(/.test(line)) {
          hits.push(`${i + 1}: ${line.trim().slice(0, 80)}`)
          guarded = true          // 같은 구간을 여러 번 세지 않는다
        }
      }
    }
    return { starts, hits }
  }

  test('id 가 바뀌면 idRef 가 따라간다 (가드의 기준점)', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile(FILE, 'utf8')
    // 주석은 걷어낸다 - 주석 처리한 줄이 살아 있는 코드로 읽히면 가드를 꺼도 통과한다
    // (2026-08-25 mutation 이 실제로 그렇게 뚫었다). `proxy.ts` 검사와 같은 처리다.
    const code = src.split(/\r?\n/).filter((l) => !l.trim().startsWith('//')).join('\n')
    assert.ok(/const\s+idRef\s*=\s*useRef\(\s*id\s*\)/.test(code),
      'idRef = useRef(id) 가 없습니다 — 늦은 응답을 구별할 기준점이 사라졌습니다')
    assert.ok(/idRef\.current\s*=\s*id/.test(code),
      'idRef.current = id 갱신이 없습니다 — 기준점이 첫 물건에 고정돼 가드가 항상 통과합니다')
  })

  test('await 로 받은 결과를 화면에 쓰기 전에 반드시 가드를 지난다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile(FILE, 'utf8')
    const { starts, hits } = unguardedWrites(src)
    assert.ok(starts.length > 0,
      'requestId 를 잡는 곳이 없습니다 — 이 검사가 공허합니다(관용구가 바뀌었으면 함께 고치십시오)')
    assert.deepEqual(hits, [],
      'await 뒤 가드 없이 화면 상태를 바꾸는 자리가 있습니다.\n' +
      '이전/다음으로 빠르게 넘기면 **이전 물건의 응답이 지금 화면을 덮습니다** — ' +
      '오류도 로딩도 아니라 사용자는 틀린 줄 모릅니다.\n' +
      '해당 줄 앞에 `if (idRef.current !== requestId) return` 을 넣으십시오 (BUGS #210).\n' +
      hits.join('\n'))
  })

  test('검사가 공허하지 않다 — 가드를 지우면 잡힌다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile(FILE, 'utf8')
    // 실제 파일은 건드리지 않는다. 가드 줄만 지운 사본에 **같은 판정 함수**를 돌린다.
    const mutated = src.split(/\r?\n/).filter((l) => !GUARD.test(l)).join('\n')
    const { hits } = unguardedWrites(mutated)
    assert.ok(hits.length > 0,
      '가드를 전부 지웠는데도 탐지되지 않습니다 — 이 검사는 아무것도 지키지 못합니다')
  })

  // ★★ 2026-08-26 (BUGS #225) — 위 검사에는 **구멍이 있었다.**
  //
  //   `unguardedWrites()` 는 `const requestId = id` 를 잡는 곳에서**만** 시작한다.
  //   즉 가드를 **선언조차 하지 않은** 핸들러는 아예 훑지 않는다 — 검사 대상이 되려면
  //   먼저 가드를 갖고 있어야 하는, 자기 참조적인 조건이다.
  //
  //   그래서 등기부/구독 핸들러 다섯 개(`performRegistryRequest`,
  //   `handleRegistryRequest`, `handleSubscribe`, `handlePayOverage`,
  //   `handleDownloadRegistry`)가 **전부 무방비인 채로 초록불**이었다.
  //   `docs/BETA_RELEASE_CHECKLIST.md` 는 그것을 "다음 후보"로 적어 두기까지 했는데,
  //   검사는 그동안 아무 말도 하지 않았다.
  //
  //   영향은 문구가 아니다. `registryRequest` 는 **다운로드 URL**
  //   (`/api/v1/registry-requests/{id}/download`)과 **결제 금액**을 만든다 —
  //   이전 물건의 값이 남으면 새 물건 화면에서 **다른 물건의 등기부를 받는다.**
  //
  //   이 검사는 방향을 뒤집는다: "가드를 선언한 곳이 옳은가"가 아니라
  //   **"가드를 선언해야 하는 곳이 전부 선언했는가"** 를 본다.
  function handlersNeedingGuard(source) {
    const lines = source.split(/\r?\n/)
    const out = []
    lines.forEach((l, i) => {
      const m = /^(\s*)(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)/.exec(l)
      if (!m) return
      const [, , name, args] = m
      // 함수 본문을 중괄호 깊이로 잘라 낸다(고정 줄 수로 훑으면 다음 함수를 끌어온다).
      let depth = 0
      let started = false
      const body = []
      for (let j = i; j < lines.length; j += 1) {
        for (const ch of lines[j]) {
          if (ch === '{') { depth += 1; started = true }
          else if (ch === '}') depth -= 1
        }
        body.push(lines[j])
        if (started && depth <= 0) break
      }
      const code = body.filter((x) => !x.trim().startsWith('//'))
      const awaitAt = code.findIndex((x) => /\bawait\b/.test(x))
      if (awaitAt < 0) return
      const writesAfterAwait = code
        .slice(awaitAt + 1)
        .some((x) => /\bset[A-Z]\w*\(/.test(x))
      if (!writesAfterAwait) return
      const declares = code.some((x) => /const\s+requestId\s*=\s*id\b/.test(x))
      const takesParam = /\brequestId\b/.test(args)
      const writes = code
        .slice(awaitAt + 1)
        .flatMap((x) => [...x.matchAll(/\bset([A-Z]\w*)\(/g)].map((mm) => `set${mm[1]}`))
      out.push({ name, line: i + 1, guarded: declares || takesParam, writes: [...new Set(writes)] })
    })
    return out
  }

  // ★ 면제는 **좁게** 준다 (BUGS #225).
  //
  //   `requireToken()` 은 await 뒤에 `setAccessToken()` 하나만 쓴다. 그 값은
  //   **물건에 딸린 것이 아니라 사용자 세션 토큰**이라, 물건을 넘긴 뒤에 반영돼도
  //   틀린 것이 아니다(오히려 같은 토큰이라 반영하는 편이 맞다).
  //
  //   그렇다고 함수 이름만으로 통째로 빼 주면, 나중에 그 함수에 **물건에 딸린**
  //   상태 쓰기가 하나 들어와도 영원히 조용해진다 — 그것이 #218 이 지적한
  //   "면제가 아니라 같은 강도로 검사하게 고친다" 는 자리다.
  //   그래서 **어떤 상태를 쓰는지까지** 고정한다. 목록에 없는 쓰기가 생기면 다시 붉어진다.
  const GUARD_EXEMPT = { requireToken: ['setAccessToken'] }

  test('★ await 뒤에 화면을 바꾸는 핸들러는 **빠짐없이** 가드를 선언한다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile(FILE, 'utf8')
    const handlers = handlersNeedingGuard(src)
    assert.ok(handlers.length >= 5,
      `가드가 필요한 핸들러를 ${handlers.length}개밖에 못 찾았습니다 — 검사가 공허합니다`)

    // 면제 대상은 **쓰는 상태가 목록과 정확히 같을 때만** 면제된다.
    const exemptDrift = handlers
      .filter((h) => GUARD_EXEMPT[h.name])
      .filter((h) => h.writes.some((w) => !GUARD_EXEMPT[h.name].includes(w)))
      .map((h) => `${h.line}: ${h.name} -> ${h.writes.join(', ')}`)
    assert.deepEqual(exemptDrift, [],
      '가드 면제 함수가 목록에 없는 상태를 쓰기 시작했습니다.\n' +
      '그 상태가 **물건에 딸린 것**이면 면제를 거두고 requestId 가드를 넣으십시오 (BUGS #225).\n' +
      exemptDrift.join('\n'))

    const missing = handlers
      .filter((h) => !h.guarded && !GUARD_EXEMPT[h.name])
      .map((h) => `${h.line}: ${h.name}`)
    assert.deepEqual(missing, [],
      'await 뒤에 화면 상태를 바꾸면서 `requestId` 를 잡지 않는 핸들러가 있습니다.\n' +
      '위 unguardedWrites() 검사는 requestId 를 잡는 곳에서만 시작하므로 ' +
      '**이런 핸들러는 검사 대상에서 통째로 빠집니다**(BUGS #225).\n' +
      '해당 함수 앞부분에 `const requestId = id` 를 넣고 await 뒤 쓰기마다 ' +
      '`if (idRef.current !== requestId) return` 을 두십시오.\n' +
      missing.join('\n'))
  })

  test('검사가 공허하지 않다 — requestId 선언을 지우면 잡힌다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile(FILE, 'utf8')
    // 실제 파일은 건드리지 않는다. 선언 줄만 지운 사본에 **같은 판정 함수**를 돌린다.
    const mutated = src
      .split(/\r?\n/)
      .filter((l) => !/const\s+requestId\s*=\s*id\b/.test(l))
      .join('\n')
    const missing = handlersNeedingGuard(mutated)
      .filter((h) => !h.guarded && !GUARD_EXEMPT[h.name])
    assert.ok(missing.length > 0,
      'requestId 선언을 전부 지웠는데도 탐지되지 않습니다 — 이 검사는 아무것도 지키지 못합니다')
  })
})

describe('면적 조건 — 두 컬럼은 판별 합집합이다 (BUGS #239) — 소스 계약', () => {
  // 이 검사가 지키는 것은 "숫자가 맞는가"가 아니라 **틀린 전제가 되살아나지 않는가**이다.
  //
  // 2026-08-26 실측(auction_item 2,558행 전수):
  //   건물면적만 1,535(60.0%) / 토지면적만 1,006(39.3%) / 둘 다 보유 0 / 둘 다 없음 17
  // 한 물건은 두 면적 중 하나만 갖는다. 그런데 세 파일이 backfill_area.py 의
  // "둘 다 없음 16행(=커버리지 99.3% 의 여집합)"을 **각 컬럼의 미보유 행 수**로 잘못
  // 옮겨 적고("면적 미상 = 차량/선박 16건"), 그 전제 위에서 두 면적을 AND 로 묶었다.
  // 결과는 UI 드롭다운 156개 조합이 **전부 0건**인 죽은 검색 경로였다.
  const FILES = ['src/app/search/SearchForm.tsx', 'api/v1/search.py']

  test('면적 미상을 "차량/선박 16건"으로 단정하는 서술이 남아있지 않다', async () => {
    const { promises: fs } = await import('node:fs')
    for (const file of FILES) {
      const src = await fs.readFile(file, 'utf8')
      // "16건/16행" 과 "차량/선박" 이 같은 줄에 함께 오는 형태만 잡는다.
      // (17행이라는 사실 자체를 적는 것은 정당하므로 문구 전체를 금지하지 않는다)
      for (const line of src.split('\n')) {
        assert.ok(
          !(/차량\/선박/.test(line) && /16\s*(건|행)/.test(line)),
          `${file}: 면적 미상을 '차량/선박 16건'으로 단정하는 서술이 되살아났습니다 -> ${line.trim()}`
        )
      }
    }
  })

  test('검색 백엔드가 두 면적 계열을 OR 로 묶는다 (AND 회귀 방지)', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile('api/v1/search.py', 'utf8')
    const code = src.split('\n').filter((l) => !l.trim().startsWith('#')).join('\n')
    assert.ok(
      /area_families/.test(code),
      'api/v1/search.py 에 면적 계열 묶음(area_families)이 없습니다'
    )
    // ★ 여기서 그냥 `" OR ".join` 을 찾으면 안 된다 — 바로 위 property_type 다중선택이
    //   같은 표현을 쓰고 있어서, 면적 쪽을 AND 로 되돌려도 초록으로 남는다.
    //   (이 검사를 처음 쓸 때 실제로 그렇게 써서 변이 N1 이 생존했다.)
    //   면적 계열을 묶는 **그 식 자체**가 OR 인지를 본다.
    //
    // ★★ 줄 단위로 보면 안 된다 — 두 번째 실수. `area_clause = " OR ".join(` 와
    //   `for c, _ in area_families)` 가 서로 다른 줄로 갈리는 순간(줄바꿈 하나로)
    //   검사가 붉어졌다. 공백을 뭉개서 **식 단위**로 본다.
    const flat = code.replace(/\s+/g, ' ')
    assert.ok(
      /area_clause\s*=/.test(flat),
      '면적 계열을 묶는 area_clause 를 찾지 못했습니다'
    )
    const areaExpr = flat.slice(flat.indexOf('area_clause ='))
    assert.ok(
      /^area_clause = " OR "\.join\(/.test(areaExpr),
      `면적 계열을 OR 로 묶는 코드가 사라졌습니다 — AND 로 되돌아가면 항상 0건입니다 -> ${areaExpr.slice(0, 120)}`
    )
    assert.ok(
      /area_families/.test(areaExpr.slice(0, 200)),
      `area_clause 가 area_families 로부터 만들어지지 않습니다 -> ${areaExpr.slice(0, 120)}`
    )
    // 계열별 조건을 개별 conditions 로 바로 붙이던 옛 형태가 되살아나지 않았는지 본다.
    for (const dead of [
      'conditions.append("building_area >= ?")',
      'conditions.append("land_area >= ?")',
    ]) {
      assert.ok(
        !code.includes(dead),
        `면적 조건을 개별 AND 로 붙이던 옛 코드가 되살아났습니다: ${dead}`
      )
    }
  })
})
