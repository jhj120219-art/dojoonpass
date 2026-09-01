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

// ================================================================
// 표시 로케일 고정 — 소스 계약 (2026-08-31 신설)
//
// ## 무엇을 막는가
//
// `x.toLocaleString()` / `toLocaleDateString()` 를 **인자 없이** 부르면 구분자와
// 날짜 형식을 보는 사람의 브라우저가 정한다. 실측:
//
//     (12900).toLocaleString('de-DE')  ->  "12.900"
//
// 청구 금액이 그렇게 나가면 한국식으로는 12.9 로 읽힌다. 오류도 로그도 없다.
// 이 저장소는 날짜에서는 이미 'ko-KR' 을 명시하고 있었는데(3곳) 숫자만 빠져 있었고,
// 그 결과 **같은 관심사에 규칙이 둘**이었다.
//
// ## 왜 소스 검사인가
//
// 실행 로케일이 ko-KR/en-US 이면 두 방식의 출력이 **완전히 같다.** 즉 이 결함은
// 이 PC 에서 값을 찍어 보는 방식으로는 영원히 드러나지 않는다. 소스에서 막아야 한다.
// ================================================================

describe('표시 로케일이 고정돼 있다 (2026-08-31) — 소스 계약', () => {
  // 문자열/주석 오탐을 줄이기 위해 주석을 걷어낸 뒤 본다.
  // (`https://` 의 `//` 를 주석으로 오인하지 않도록 앞 문자가 `:` 인 경우는 남긴다.)
  const stripComments = (code) =>
    code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')

  const BARE = /\.toLocale(?:String|DateString|TimeString)\(\s*\)/g

  const listSources = async () => {
    const { promises: fs } = await import('node:fs')
    const out = []
    const walk = async (dir) => {
      for (const e of await fs.readdir(dir, { withFileTypes: true })) {
        const p = `${dir}/${e.name}`
        if (e.isDirectory()) await walk(p)
        else if (/\.tsx?$/.test(e.name)) out.push(p)
      }
    }
    await walk('src')
    return out
  }

  test('검사가 공허하지 않다 — 파일을 실제로 찾았고 탐지기가 동작한다', async () => {
    const files = await listSources()
    assert.ok(files.length > 20, `src 아래 .ts/.tsx 를 제대로 못 찾았습니다: ${files.length}개`)
    // 탐지기 자체를 합성 입력으로 증명한다.
    assert.ok(BARE.test('const s = n.toLocaleString()'), '탐지기가 인자 없는 호출을 못 잡습니다')
    BARE.lastIndex = 0
    assert.ok(!BARE.test("const s = n.toLocaleString('ko-KR')"), '탐지기가 로케일 지정까지 잡습니다(오탐)')
    BARE.lastIndex = 0
    // 주석 제거가 코드를 지우지 않는지도 같은 자리에서 본다.
    assert.ok(stripComments("const u = 'https://a.b' // note").includes('https://a.b'),
      '주석 제거가 URL 을 망가뜨립니다')
    assert.ok(!stripComments('a() // x.toLocaleString()').includes('toLocaleString'),
      '주석이 제거되지 않습니다')
  })

  test('★ src 어디에도 인자 없는 toLocale* 호출이 없다', async () => {
    const { promises: fs } = await import('node:fs')
    const offenders = []
    for (const file of await listSources()) {
      const code = stripComments(await fs.readFile(file, 'utf8'))
      BARE.lastIndex = 0
      if (BARE.test(code)) offenders.push(file)
    }
    assert.deepEqual(
      offenders, [],
      `로케일을 지정하지 않은 표시 포맷이 있습니다(보는 사람의 브라우저가 구분자를 정합니다): ${offenders.join(', ')}`
    )
  })

  test('청구 금액 표기가 formatWon 한 곳에서만 만들어진다(상세 구독 카드 포함)', async () => {
    const { promises: fs } = await import('node:fs')
    const detail = await fs.readFile('src/app/properties/[id]/page.tsx', 'utf8')
    // 2026-08-31 이전에는 이 화면이 formatWon 을 import 해 두고도 구독/초과결제 5곳에서
    // `.toLocaleString() + '원'` 을 손으로 다시 적고 있었다(중복 구현).
    assert.ok(
      !/toLocaleString\([^)]*\)\s*(\+\s*'원'|}원)/.test(stripComments(detail)),
      '상세 페이지가 원 단위 표기를 손으로 다시 만듭니다 — formatWon 을 쓰십시오'
    )
    assert.ok(detail.includes('formatWon('), '상세 페이지가 formatWon 을 쓰지 않습니다')
  })

  test('공용 포맷 함수가 로케일을 실제로 고정한다', async () => {
    const { promises: fs } = await import('node:fs')
    const lib = await fs.readFile('src/lib/format.ts', 'utf8')
    assert.ok(/export const DISPLAY_LOCALE = 'ko-KR'/.test(lib),
      'src/lib/format.ts 의 DISPLAY_LOCALE 이 ko-KR 로 고정돼 있지 않습니다')
    assert.ok(/export function formatNumber/.test(lib), 'formatNumber 가 없습니다')
    // formatWon 이 formatNumber 를 우회해 직접 만들면 규칙이 다시 갈린다.
    const won = lib.slice(lib.indexOf('export function formatWon'))
    assert.ok(/formatNumber\(amount\)/.test(won.slice(0, 200)),
      'formatWon 이 formatNumber 를 거치지 않습니다(표기 규칙이 갈립니다)')
  })
})


// ================================================================
// D-day 계산이 한 곳에만 있다 — 소스 계약 (2026-08-31 신설)
//
// 이 함수는 원래 `src/app/search/ResultList.tsx`(JSX) 안에 있었고 상세 페이지가
// **다른 라우트의 컴포넌트 파일에서** 꺼내 쓰고 있었다. 그래서 (1) Node 타입
// 스트리핑으로 import 할 수 없어 동작 테스트가 없었고, (2) 화면이 화면을 import 하는
// 계층 우회가 생겼다. `src/lib/format.ts` 로 옮기면서 그 둘을 함께 닫는다.
// ================================================================

describe('D-day 계산의 위치와 기준 (2026-08-31) — 소스 계약', () => {
  const read = async (p) => (await (await import('node:fs')).promises).readFile(p, 'utf8')

  test('formatDday 가 공용 모듈 한 곳에만 정의된다', async () => {
    const lib = await read('src/lib/format.ts')
    assert.ok(/export function formatDday/.test(lib),
      'src/lib/format.ts 에 formatDday 가 없습니다')
    for (const file of ['src/app/search/ResultList.tsx', 'src/app/properties/[id]/page.tsx']) {
      const src = await read(file)
      assert.ok(!/function formatDday/.test(src),
        `${file} 에 formatDday 지역 사본이 되살아났습니다(중복 정의)`)
    }
  })

  test('화면이 다른 라우트의 컴포넌트에서 유틸을 가져오지 않는다', async () => {
    const detail = await read('src/app/properties/[id]/page.tsx')
    assert.ok(!/from '@\/app\/search\/ResultList'/.test(detail),
      '상세 페이지가 검색 화면의 컴포넌트 파일에서 유틸을 가져옵니다(계층 우회)')
    assert.ok(/formatDday/.test(detail) && /from '@\/lib\/format'/.test(detail),
      '상세 페이지가 공용 모듈에서 formatDday 를 가져오지 않습니다')
  })

  test('"오늘" 이 보는 사람의 시계가 아니라 한국 시각으로 정해진다', async () => {
    const lib = await read('src/lib/format.ts')
    assert.ok(/export const DISPLAY_TIME_ZONE = 'Asia\/Seoul'/.test(lib),
      'DISPLAY_TIME_ZONE 이 Asia/Seoul 로 고정돼 있지 않습니다')
    // 옛 구현의 형태 — 로컬 자정으로 되돌리면 시간대마다 하루씩 어긋난다.
    assert.ok(!/setHours\(0,\s*0,\s*0,\s*0\)/.test(lib),
      '로컬 자정 기준 계산이 되살아났습니다(보는 사람의 시계를 따릅니다)')
    const body = lib.slice(lib.indexOf('export function formatDday'))
    assert.ok(/todayInDisplayZone\(now\)/.test(body.slice(0, 400)),
      'formatDday 가 todayInDisplayZone 을 거치지 않습니다')
  })
})


// ================================================================
// 검색 타입 파일이 미지원 정본과 어긋나지 않는다 (2026-08-31 신설)
//
// 2026-08-26 에 면적 4종이 구현되면서 `SearchForm.tsx` 와
// `tests/_search_param_contract.mjs` 는 갱신됐는데 **`src/app/search/types.ts` 만**
// "아래 4개 필드는 백엔드가 읽지 않는다"를 계속 적고 있었다(2026-08-31 발견).
//
// 이 종류의 드리프트는 실행해도 드러나지 않는다 — 타입은 맞고 검색도 잘 돈다.
// 드러나는 순간은 누군가 그 주석을 믿고 **"죽은 파라미터니 지우자"** 로 갈 때이고,
// 그때 실동작 필터가 사라진다. 그래서 "미지원"이라는 **서술**을 정본과 대조한다.
// ================================================================

describe('검색 타입 파일의 미지원 서술이 정본과 같다 (2026-08-31) — 소스 계약', () => {
  const TYPES = 'src/app/search/types.ts'

  // 프런트가 보내는 파라미터가 types.ts 에서 "백엔드가 읽지 않는다" 류의 서술과
  // **같은 주석 블록**에 묶여 있는지 본다.
  // 문장 전체를 본다. '미지원' 같은 한 단어는 정본을 가리키는 정상 문장
  // ("미지원 파라미터의 정본은 ...")에도 나와 오탐이 된다.
  const NEGATIONS = ['백엔드가 읽지 않는다', '백엔드가 받지 않는다',
                     '백엔드가 아직 받지 않는다', '아직 구현되지 않음']

  // 사료(옛 문장 인용)와 살아 있는 주장을 **표기로** 가른다 — 산문 판정은 우회된다.
  // 이 저장소는 정정할 때 옛 문장을 **큰따옴표로 인용**한다. 인용 밖에 남은 부정
  // 서술만 "지금도 그렇다"는 주장이다. `~~취소선~~`도 같은 취급(마크다운 표기).
  const stripQuoted = (text) => text.replace(/"[^"]*"/g, ' ').replace(/~~[^~]*~~/g, ' ')

  test('검사가 공허하지 않다 — 정본과 타입 파일을 실제로 읽었다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile(TYPES, 'utf8')
    assert.ok(src.includes('min_building_area'), 'types.ts 에서 면적 파라미터를 찾지 못했습니다')
    assert.ok(KNOWN_UNSUPPORTED.size >= 1, '정본 목록이 비었습니다')

    // 인용/취소선 제거기가 실제로 동작한다(공허한 통과 방지).
    const strip = (t) => t.replace(/"[^"]*"/g, ' ').replace(/~~[^~]*~~/g, ' ')
    assert.ok(!strip('// 예전엔 "백엔드가 읽지 않는다" 였다').includes('백엔드가 읽지 않는다'),
      '인용된 옛 문장이 제거되지 않습니다')
    assert.ok(strip('// 백엔드가 읽지 않는다').includes('백엔드가 읽지 않는다'),
      '인용 밖 서술까지 지워집니다(검사가 공허해집니다)')
  })

  test('★ 백엔드가 지원하는 파라미터를 types.ts 가 미지원이라고 적지 않는다', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile(TYPES, 'utf8')
    const api = await fs.readFile('api/v1/search.py', 'utf8')

    const backend = new Set()
    for (const m of api.matchAll(/^\s{4}(\w+)\s*:\s*[^=]+=\s*Query\(/gm)) backend.add(m[1])
    assert.ok(backend.size > 10, `백엔드 파라미터 추출 실패 (${backend.size}개)`)

    const lines = src.split('\n')
    const offenders = []
    for (const name of backend) {
      const idx = lines.findIndex((l) => new RegExp(String.raw`^\s*${name}\?:`).test(l))
      if (idx === -1) continue
      // 선언 바로 위의 연속된 주석 블록만 본다(다른 필드의 주석까지 넘어가지 않는다).
      const block = []
      for (let i = idx - 1; i >= 0; i--) {
        const l = lines[i].trim()
        if (l.startsWith('//')) { block.push(l); continue }
        // 하나의 주석이 나란한 여러 선언을 함께 덮는다(면적 4줄). 그래서 아직
        // 주석을 만나기 전이면 이웃 선언을 건너뛴다. 그러나 **이미 자기 주석을
        // 읽은 뒤라면** 멈춘다 - 계속 올라가면 윗 필드의 주석까지 자기 것으로
        // 삼아, 전혀 상관없는 page/size/sort_by 가 함께 걸린다(실제로 걸렸다).
        if (block.length === 0 && /^[a-z_]+\??:/.test(l)) continue
        break
      }
      const text = stripQuoted(block.join(' '))
      if (NEGATIONS.some((n) => text.includes(n))) offenders.push(name)
    }
    assert.deepEqual(
      offenders.sort(), [],
      `백엔드가 이미 받는 파라미터를 types.ts 가 미지원으로 서술합니다 — 그 주석을 믿으면 실동작 필터를 지우게 됩니다: ${offenders.join(', ')}`
    )
  })

  test('미지원 정본이 한 곳뿐이다(타입 파일이 두 번째 목록을 만들지 않는다)', async () => {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile(TYPES, 'utf8')
    assert.ok(
      !/KNOWN_UNSUPPORTED\s*=/.test(src),
      'types.ts 가 미지원 목록을 따로 정의합니다 — 정본은 tests/_search_param_contract.mjs 하나입니다'
    )
    // 남은 미지원 항목은 **자기 주석 블록에서** 정본을 가리켜야 한다.
    // 파일 어딘가에 한 번 언급되는 것으로는 부족하다 — 다른 필드의 주석이
    // 대신 통과시켜 주면 그 항목은 다시 고아가 된다.
    const lines = src.split('\n')
    for (const key of KNOWN_UNSUPPORTED) {
      const idx = lines.findIndex((l) => new RegExp(String.raw`^\s*${key}\??:`).test(l))
      assert.ok(idx !== -1, `types.ts 에 ${key} 선언이 없습니다`)
      const block = []
      for (let i = idx - 1; i >= 0; i--) {
        const l = lines[i].trim()
        if (l.startsWith('//')) { block.push(l); continue }
        break
      }
      assert.ok(
        block.join(' ').includes('_search_param_contract'),
        `types.ts 의 ${key} 주석이 미지원 정본(tests/_search_param_contract.mjs)을 가리키지 않습니다`
      )
    }
  })
})


// ================================================================
// 서비스명 표기 — 소스 계약 (2026-08-31 신설)
//
// `docs/decision-log.md` "Service Name": 서비스명은 **"콕찰"** 이다.
// `docs/frontend.md` "절대 변경하면 안 되는 것": `"도준패스"/"도준 경매 패스" 사용 금지`.
//
// ## 왜 지금 생겼나 — 확정된 정책인데 지키는 검사가 없었다
//
// 2026-08-31 실측에서 **가장 최근에 추가된 화면**(2026-08-28 Sprint 270,
// 마이리스트 가져오기)이 사용자에게 구 브랜드명을 두 번 보여주고 있었다.
//
//     src/app/favorites/import/page.tsx:245  "... 도준패스 물건과 맞춰 봅니다"
//     src/app/favorites/import/page.tsx:421  "도준패스에 아직 없는 사건이거나 ..."
//
// 나머지 화면(`layout.tsx` / `login` / `SiteHeader`)은 전부 "콕찰"이다. 즉 정책이
// 없어서가 아니라 **정책을 확인하지 않고 새 화면을 만들어서** 갈라졌다. 문서에만
// 있는 규칙은 다음 기능에서 다시 깨진다 — 그래서 검사로 옮긴다.
//
// 사용자에게 보이지 않는 자리(주석의 경위 서술 등)까지 막지는 않는다.
// 금지 대상은 **화면에 렌더되는 문구**다.
// ================================================================

describe('서비스명이 "콕찰" 하나다 (2026-08-31) — 소스 계약', () => {
  const FORBIDDEN = ['도준패스', '도준 경매 패스', '도준경매패스']

  const listSources = async () => {
    const { promises: fs } = await import('node:fs')
    const out = []
    const walk = async (dir) => {
      for (const e of await fs.readdir(dir, { withFileTypes: true })) {
        const p = `${dir}/${e.name}`
        if (e.isDirectory()) await walk(p)
        else if (/\.tsx?$/.test(e.name)) out.push(p)
      }
    }
    await walk('src')
    return out
  }

  // 주석은 경위를 적는 자리다 — 화면 문구만 본다.
  const stripComments = (code) =>
    code.replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
        .replace(/(^|[^:])\/\/[^\n]*/g, '$1')

  test('검사가 공허하지 않다 — 파일을 찾았고 탐지기가 동작한다', async () => {
    const files = await listSources()
    assert.ok(files.length > 20, `src 아래 .ts/.tsx 를 못 찾았습니다: ${files.length}개`)
    assert.ok(stripComments('const s = "도준패스 물건"').includes('도준패스'),
      '탐지기가 화면 문구를 못 잡습니다')
    assert.ok(!stripComments('// 구 브랜드명 도준패스 를 쓰지 않는다').includes('도준패스'),
      '주석까지 잡습니다(오탐)')
  })

  test('★ 화면 문구에 구 브랜드명이 없다', async () => {
    const { promises: fs } = await import('node:fs')
    const offenders = []
    for (const file of await listSources()) {
      const code = stripComments(await fs.readFile(file, 'utf8'))
      for (const bad of FORBIDDEN) {
        if (code.includes(bad)) offenders.push(`${file} (${bad})`)
      }
    }
    assert.deepEqual(
      offenders, [],
      `구 브랜드명이 화면에 나갑니다 — 서비스명은 "콕찰"입니다(docs/decision-log.md "Service Name"): ${offenders.join(', ')}`
    )
  })

  test('확정된 서비스명을 실제로 쓰고 있다', async () => {
    const { promises: fs } = await import('node:fs')
    const layout = await fs.readFile('src/app/layout.tsx', 'utf8')
    assert.ok(layout.includes('콕찰'), 'layout.tsx 의 metadata 에 서비스명이 없습니다')
    const header = await fs.readFile('src/components/SiteHeader.tsx', 'utf8')
    assert.ok(header.includes('콕찰'), '공통 헤더에 서비스명이 없습니다')
  })
})


// ================================================================
// 카드 면적의 출처 — 소스 계약 (2026-08-31 신설)
//
// 면적 규칙이 두 곳에 있다(백엔드 컬럼 = 검색 필터가 쓰는 값 / 프런트 주소 파서).
// 화면이 다시 주소 파서만 쓰면 **필터와 표시가 다른 사실을 말한다** — 실제로
// 단위가 '평'인 7건이 그랬다(걸러 놓고 카드는 빈 칸).
// ================================================================

describe('검색 카드가 서버 면적을 먼저 쓴다 (2026-08-31) — 소스 계약', () => {
  const read = async (p) => (await (await import('node:fs')).promises).readFile(p, 'utf8')

  test('ResultList 가 displayArea 를 통해 면적을 얻는다', async () => {
    const src = await read('src/app/search/ResultList.tsx')
    assert.ok(/const area = displayArea\(item\)/.test(src),
      '검색 카드가 displayArea 를 쓰지 않습니다 — 필터가 쓰는 값과 다른 숫자를 보여주게 됩니다')
    assert.ok(!/parseArea\(/.test(src),
      '검색 카드가 주소 파서를 직접 부릅니다 — 폴백은 displayArea 안에서만 합니다')
  })

  test('폴백은 남아 있다 (구 백엔드에서 카드가 비지 않는다)', async () => {
    const lib = await read('src/lib/format.ts')
    const body = lib.slice(lib.indexOf('export function displayArea'))
    assert.ok(/serverArea\([^)]*\)\s*\?\?\s*parseArea\(/.test(body.slice(0, 400)),
      'displayArea 의 우선순위(서버 -> 주소)가 깨졌습니다')
  })

  test('타입이 응답에 실리는 면적 키를 선언한다', async () => {
    const types = await read('src/app/search/types.ts')
    const item = types.slice(types.indexOf('export type SearchResultItem'))
    for (const key of ['building_area', 'land_area']) {
      assert.ok(new RegExp(String.raw`^\s*${key}\?:`, 'm').test(item),
        `SearchResultItem 에 ${key} 선언이 없습니다 — 응답에는 실려 있습니다`)
    }
  })

  test('백엔드가 실제로 그 키를 내려준다', async () => {
    const api = await read('api/v1/search.py')
    const fn = api.slice(api.indexOf('def row_to_item'))
    for (const key of ['building_area', 'land_area']) {
      assert.ok(fn.slice(0, 2000).includes(`"${key}"`),
        `row_to_item 이 ${key} 를 내려주지 않습니다 — 프런트 계약이 앞서 나갔습니다`)
    }
  })
})


// ================================================================
// 최저가율 표기가 한 곳에서만 만들어진다 — 소스 계약 (2026-08-31 신설)
//
// 검색 카드와 상세가 같은 필드(`bid_rate`)를 **각자** 퍼센트로 바꾸고 있었고,
// 상세 쪽에는 값 없음 가드가 없어 "0.0%" 를 지어냈다.
//
// ★ 라벨이 화면마다 다른 것(검색 "최저가율" / 상세 "입찰가율")은 **의도된 상태**다 —
//   `search/00_SEARCH_MVP.md` §5.2 와 `docs/FRONTEND_MASTER_SPEC.md` §9.2 가 각각
//   그렇게 정하고 있다. 여기서 고정하는 것은 **숫자 표기 규칙 하나**뿐이다.
// ================================================================

describe('최저가율 표기가 한 곳에서만 만들어진다 (2026-08-31) — 소스 계약', () => {
  const read = async (p) => (await (await import('node:fs')).promises).readFile(p, 'utf8')
  const SCREENS = ['src/app/search/ResultList.tsx', 'src/app/properties/[id]/page.tsx']

  test('공용 함수가 존재하고 값 없음을 지어내지 않는다', async () => {
    const lib = await read('src/lib/format.ts')
    assert.ok(/export function formatBidRate/.test(lib), 'formatBidRate 가 공용에 없습니다')
    const body = lib.slice(lib.indexOf('export function formatBidRate'))
    assert.ok(/return '-'/.test(body.slice(0, 300)),
      'formatBidRate 에 값 없음 가드가 없습니다 — null 이 "0.0%" 로 찍힙니다')
  })

  test('★ 화면이 퍼센트 계산을 손으로 다시 하지 않는다', async () => {
    const offenders = []
    for (const file of SCREENS) {
      const src = await read(file)
      // `bid_rate * 100` / `bidRate * 100` 같은 직접 계산.
      if (/bid_?[Rr]ate\s*\*\s*100/.test(src)) offenders.push(file)
      if (/function formatBidRate/.test(src)) offenders.push(`${file} (지역 사본)`)
    }
    assert.deepEqual(offenders, [],
      `최저가율을 화면에서 직접 계산합니다 — formatBidRate 를 쓰십시오: ${offenders.join(', ')}`)
  })

  test('두 화면 모두 공용 함수를 실제로 쓴다 (검사가 공허하지 않다)', async () => {
    for (const file of SCREENS) {
      const src = await read(file)
      assert.ok(/formatBidRate\(/.test(src), `${file} 이 formatBidRate 를 쓰지 않습니다`)
      assert.ok(/from '@\/lib\/format'/.test(src), `${file} 이 공용 모듈에서 가져오지 않습니다`)
    }
    // 탐지기 자체 증명.
    assert.ok(/bid_?[Rr]ate\s*\*\s*100/.test('x = property.bid_rate * 100'),
      '직접 계산 탐지기가 동작하지 않습니다')
    assert.ok(!/bid_?[Rr]ate\s*\*\s*100/.test('formatBidRate(property.bid_rate)'),
      '탐지기가 정상 호출까지 잡습니다(오탐)')
  })

  test('문서가 정한 화면별 라벨이 그대로 있다', async () => {
    // 라벨 통일은 제품 결정이라 하지 않았다. 다만 **문서와 어긋나지는 않게** 고정한다.
    const list = await read('src/app/search/ResultList.tsx')
    assert.ok(list.includes('최저가율'),
      '검색 카드 라벨이 search/00_SEARCH_MVP.md §5.2 와 다릅니다')
    const detail = await read('src/app/properties/[id]/page.tsx')
    assert.ok(detail.includes('입찰가율'),
      '상세 라벨이 docs/FRONTEND_MASTER_SPEC.md §9.2 와 다릅니다')
  })
})


// ================================================================
// 인증 필요 응답 ↔ 프런트 타입 — 소스 대조 (2026-08-31 신설)
//
// ## 왜 소스로 보나
//
// 공개 API 는 `tests/frontend-contract.test.mjs` 가 **살아 있는 서버**로 대조한다.
// 인증이 필요한 목록(`/favorites`, `/recent-items`)은 같은 방법을 쓰려면 JWT 가 필요하고,
// 그 서명 시크릿을 읽는 것은 승인 영역이다(`docs/CLAUDE.md` — Secret 값 열람 금지).
// 그래서 **같은 질문에 소스로 답한다** — 라우터가 만드는 dict 의 키와 TS 인터페이스의 키.
//
// ## 무엇을 잡았나
//
// 2026-08-31 이 검사를 만들면서 실제 드리프트를 하나 찾았다.
//
//     GET /api/v1/favorites  ->  note_source (favorite_notes.source)
//     src/app/favorites/page.tsx:FavoriteItem  ->  선언 없음
//
// 검색·상세에서 고친 것과 같은 모양이다(면적 4종 / sido·sigungu·dong).
// 선언되지 않은 키는 "응답에 없는 것"으로 읽혀 **이미 있는 데이터를 다시 만들게** 한다.
// ================================================================

describe('인증 필요 응답 ↔ 프런트 타입 (2026-08-31) — 소스 계약', () => {
  const read = async (p) => (await (await import('node:fs')).promises).readFile(p, 'utf8')

  /** 파이썬 함수 안에서 만들어지는 가장 큰 문자열-키 dict 의 키 목록. */
  async function apiKeys(file, funcName) {
    const src = await read(file)
    const at = src.indexOf(`def ${funcName}(`)
    assert.ok(at !== -1, `${file} 에서 ${funcName}() 를 찾지 못했습니다`)
    // 다음 최상위 def 까지가 그 함수다.
    const rest = src.slice(at)
    const nextDef = rest.slice(1).search(/\nsdef |\n@router|\ndef /)
    const body = nextDef === -1 ? rest : rest.slice(0, nextDef + 1)
    let best = []
    // `{ "a": ..., "b": ... }` 블록마다 키를 센다.
    for (const m of body.matchAll(/\{([\s\S]*?)\n\s*\}/g)) {
      const keys = [...m[1].matchAll(/"([a-z_][a-z0-9_]*)"\s*:/g)].map((k) => k[1])
      if (keys.length > best.length) best = keys
    }
    return new Set(best)
  }

  async function tsKeys(file, name) {
    const src = await read(file)
    const m = new RegExp(String.raw`(?:interface|type)\s+${name}\s*=?\s*\{`).exec(src)
    assert.ok(m, `${file} 에서 ${name} 선언을 찾지 못했습니다`)
    let depth = 1
    let i = m.index + m[0].length
    const start = i
    while (i < src.length && depth > 0) {
      if (src[i] === '{') depth++
      else if (src[i] === '}') depth--
      i++
    }
    let body = src.slice(start, i - 1)
    for (;;) {
      const next = body.replace(/\{[^{}]*\}/g, '')
      if (next === body) break
      body = next
    }
    const required = new Set()
    const optional = new Set()
    for (const line of body.split('\n')) {
      const code = line.split('//')[0].trim()
      const km = /^([a-zA-Z_][a-zA-Z0-9_]*)(\??)\s*:/.exec(code)
      if (!km) continue
      ;(km[2] === '?' ? optional : required).add(km[1])
    }
    return { required, optional, all: new Set([...required, ...optional]) }
  }

  const CASES = [
    ['GET /api/v1/favorites', 'api/v1/favorites.py', 'get_favorites',
     'src/app/favorites/page.tsx', 'FavoriteItem'],
    ['GET /api/v1/recent-items', 'api/v1/recent_items.py', 'get_recent_items',
     'src/app/properties/recent/page.tsx', 'RecentItem'],
  ]

  test('검사가 공허하지 않다 — 양쪽 키를 실제로 뽑았다', async () => {
    for (const [label, py, fn, ts, iface] of CASES) {
      const api = await apiKeys(py, fn)
      const t = await tsKeys(ts, iface)
      assert.ok(api.size > 10, `${label}: API 키 추출 실패 (${api.size}개)`)
      assert.ok(t.all.size > 10, `${label}: TS 키 추출 실패 (${t.all.size}개)`)
      // 두 쪽 다 아는 대표 키가 실제로 잡히는지 확인한다.
      assert.ok(api.has('case_no') && t.all.has('case_no'), `${label}: case_no 를 못 찾았습니다`)
    }
  })

  test('★ 응답의 모든 키가 타입에 선언돼 있다', async () => {
    for (const [label, py, fn, ts, iface] of CASES) {
      const api = await apiKeys(py, fn)
      const t = await tsKeys(ts, iface)
      const undeclared = [...api].filter((k) => !t.all.has(k)).sort()
      assert.deepEqual(undeclared, [],
        `${label}: 응답에는 있는데 ${iface} 에 없는 키입니다 — "응답에 없다"로 읽혀 같은 데이터를 다시 만들게 됩니다: ${undeclared.join(', ')}`)
    }
  })

  test('타입이 필수라고 적은 키가 응답에 실제로 있다', async () => {
    for (const [label, py, fn, ts, iface] of CASES) {
      const api = await apiKeys(py, fn)
      const t = await tsKeys(ts, iface)
      const phantom = [...t.required].filter((k) => !api.has(k)).sort()
      assert.deepEqual(phantom, [],
        `${label}: ${iface} 가 필수라고 적었는데 응답에 없는 키입니다: ${phantom.join(', ')}`)
    }
  })

  test('두 목록 화면이 같은 카드 필드를 받는다 (화면마다 다른 데이터가 되지 않는다)', async () => {
    // 관심물건/최근본은 같은 카드 컴포넌트 모양을 쓴다. 화면 전용 필드만 달라야 한다.
    const fav = await apiKeys('api/v1/favorites.py', 'get_favorites')
    const rec = await apiKeys('api/v1/recent_items.py', 'get_recent_items')
    const favOnly = [...fav].filter((k) => !rec.has(k)).sort()
    const recOnly = [...rec].filter((k) => !fav.has(k)).sort()
    assert.deepEqual(favOnly, ['favorited_at', 'memo', 'note_source', 'tags'],
      `관심물건에만 있는 필드가 달라졌습니다: ${favOnly.join(', ')}`)
    assert.deepEqual(recOnly, ['viewed_at'],
      `최근본에만 있는 필드가 달라졌습니다: ${recOnly.join(', ')}`)
  })
})


// ================================================================
// 마이페이지 3종 응답 ↔ 프런트 타입 (2026-08-31 신설)
//
// `/mypage` 는 기존 API 3개를 조합한 읽기 전용 화면이다(`docs/FRONTEND_MASTER_SPEC.md` §16).
// 위 관심물건/최근본과 같은 방식으로 소스 대조한다 — JWT 시크릿 열람은 승인 영역이라
// 살아 있는 서버로는 대조하지 못한다.
//
// ## 여기서는 "타입에 다 적는다"가 답이 아니다
//
// 검색·상세에서는 미선언 키를 **타입에 추가**했다(면적/주소 조각 — 화면이 쓸 수 있는 값).
// 마이페이지 쪽 미선언 키는 성격이 다르다.
//
//     user_id / updated_at / created_at   화면이 쓸 일이 없는 내부 필드
//     pg_provider / pg_transaction_id     결제 내부 식별자 (PG 연동 전이라 전부 null)
//     metadata                            결제 부가 정보(JSON 문자열)
//     completed_at                        등기부 발급 완료 시각 — **사용자에게 의미가 있다**
//
// 어느 것을 타입에 올리고 어느 것을 응답에서 뺄지는 **정보 구성/계약 축소 결정**이라
// 여기서 정하지 않는다(`docs/BUGS.md` #254 가 `tenants[]` 3키를 같은 이유로 남겨 둔 것과
// 같은 취급이다). 대신 **지금 상태를 명시적으로 적어 고정**한다 —
//   1. 목록에 없는 새 키가 응답에 생기면 실패한다 (조용히 늘지 않는다)
//   2. 목록에 있는데 응답에서 사라지면 실패한다 (죽은 예외 금지)
// ================================================================

describe('마이페이지 3종 응답 ↔ 프런트 타입 (2026-08-31) — 소스 계약', () => {
  const read = async (p) => (await (await import('node:fs')).promises).readFile(p, 'utf8')

  async function apiKeys(file, funcName) {
    const src = await read(file)
    const at = src.indexOf(`def ${funcName}(`)
    assert.ok(at !== -1, `${file} 에서 ${funcName}() 를 찾지 못했습니다`)
    const rest = src.slice(at)
    const nextDef = rest.slice(1).search(/\ndef |\n@router/)
    const body = nextDef === -1 ? rest : rest.slice(0, nextDef + 1)
    let best = []
    for (const m of body.matchAll(/\{([\s\S]*?)\n\s*\}/g)) {
      const keys = [...m[1].matchAll(/"([a-z_][a-z0-9_]*)"\s*:/g)].map((k) => k[1])
      if (keys.length > best.length) best = keys
    }
    return new Set(best)
  }

  async function tsKeys(file, name) {
    const src = await read(file)
    const m = new RegExp(String.raw`(?:interface|type)\s+${name}\s*=?\s*\{`).exec(src)
    assert.ok(m, `${file} 에서 ${name} 선언을 찾지 못했습니다`)
    let depth = 1
    let i = m.index + m[0].length
    const start = i
    while (i < src.length && depth > 0) {
      if (src[i] === '{') depth++
      else if (src[i] === '}') depth--
      i++
    }
    let body = src.slice(start, i - 1)
    for (;;) {
      const next = body.replace(/\{[^{}]*\}/g, '')
      if (next === body) break
      body = next
    }
    const required = new Set()
    const all = new Set()
    for (const line of body.split('\n')) {
      const code = line.split('//')[0].trim()
      const km = /^([a-zA-Z_][a-zA-Z0-9_]*)(\??)\s*:/.exec(code)
      if (!km) continue
      all.add(km[1])
      if (km[2] !== '?') required.add(km[1])
    }
    return { required, all }
  }

  // 응답에는 있지만 타입에 적지 않기로 **한 것**. 늘리려면 근거가 있어야 한다.
  const MYPAGE = [
    {
      label: 'GET /api/v1/subscriptions/me',
      py: 'api/v1/subscriptions.py', fn: 'row_to_subscription',
      ts: 'src/app/mypage/page.tsx', iface: 'Subscription',
      undeclared: ['created_at', 'updated_at', 'user_id'],
    },
    {
      label: 'GET /api/v1/payments',
      py: 'api/v1/payments.py', fn: 'row_to_payment',
      ts: 'src/app/mypage/page.tsx', iface: 'Payment',
      undeclared: ['metadata', 'pg_provider', 'pg_transaction_id', 'updated_at', 'user_id'],
    },
    {
      label: 'GET /api/v1/registry-requests',
      py: 'api/v1/registry.py', fn: 'get_registry_requests',
      ts: 'src/app/mypage/page.tsx', iface: 'RegistryRequest',
      // 사용자에게 의미가 있는 유일한 항목. 화면에 올릴지는 정보 구성 결정이라 SKIP.
      undeclared: ['completed_at'],
    },
  ]

  test('검사가 공허하지 않다 — 세 응답과 세 타입을 실제로 읽었다', async () => {
    for (const c of MYPAGE) {
      const api = await apiKeys(c.py, c.fn)
      const ts = await tsKeys(c.ts, c.iface)
      assert.ok(api.size >= 5, `${c.label}: API 키 추출 실패 (${api.size}개)`)
      assert.ok(ts.all.size >= 5, `${c.label}: TS 키 추출 실패 (${ts.all.size}개)`)
      assert.ok(api.has('status') && ts.all.has('status'), `${c.label}: status 를 못 찾았습니다`)
    }
  })

  test('★ 목록에 없는 새 키가 응답에 조용히 생기지 않는다', async () => {
    for (const c of MYPAGE) {
      const api = await apiKeys(c.py, c.fn)
      const ts = await tsKeys(c.ts, c.iface)
      const unexpected = [...api]
        .filter((k) => !ts.all.has(k) && !c.undeclared.includes(k))
        .sort()
      assert.deepEqual(unexpected, [],
        `${c.label}: 타입에도 없고 예외 목록에도 없는 응답 키입니다 — 타입에 올리거나 예외에 근거와 함께 적으십시오: ${unexpected.join(', ')}`)
    }
  })

  test('★ 예외 목록이 코드보다 앞서 나가지 않는다 (죽은 예외 금지)', async () => {
    for (const c of MYPAGE) {
      const api = await apiKeys(c.py, c.fn)
      const dead = c.undeclared.filter((k) => !api.has(k)).sort()
      assert.deepEqual(dead, [],
        `${c.label}: 응답에 더 이상 없는 키가 예외 목록에 남아 있습니다 — 목록에서 빼십시오: ${dead.join(', ')}`)
    }
  })

  test('타입이 필수라고 적은 키가 응답에 실제로 있다', async () => {
    for (const c of MYPAGE) {
      const api = await apiKeys(c.py, c.fn)
      const ts = await tsKeys(c.ts, c.iface)
      const phantom = [...ts.required].filter((k) => !api.has(k)).sort()
      assert.deepEqual(phantom, [],
        `${c.label}: ${c.iface} 가 필수라고 적었는데 응답에 없는 키입니다: ${phantom.join(', ')}`)
    }
  })
})


// ================================================================
// "오늘"을 UTC 로 만들지 않는다 — 소스 계약 (2026-09-01 신설)
//
// `new Date().toISOString().slice(0, 10)` 은 **UTC 날짜**다. 서버도 사용자도
// 한국인 이 제품에서는 KST 09:00 이전에 항상 하루 전이 나온다.
//
//   검색폼 퀵버튼 "당일"   -> 어제 날짜로 검색 -> 오늘 매각되는 물건이 0건
//   검색폼 퀵버튼 "+7"     -> 8일 범위(시작만 밀리고 끝은 경계를 다시 넘는다)
//   내보내기 파일명          -> 어제 날짜가 붙은 CSV
//
// 오류도 빈 화면도 아니고 "그날은 물건이 없네"로 보이는 것이 이 결함의 모양이다.
// `formatDday()` 가 이미 `DISPLAY_TIME_ZONE` 으로 고친 것과 **같은 기준**을
// 입력쪽에도 적용한다 — 새 정책이 아니라 선언된 정책의 적용 범위다.
// ================================================================

describe('"오늘"을 UTC 로 만들지 않는다 (2026-09-01) — 소스 계약', () => {
  const stripComments = (code) =>
    code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')

  // 날짜를 **UTC 로 잘라내는** 모양. 수신자를 가리지 않는 것이 핵심이다 —
  // 고치기 전 SearchForm.tsx 는 `const toISODate = (d: Date) => d.toISOString().slice(0, 10)`
  // 처럼 **한 단계 건너서** 썼고, `new Date()` 에 붙은 것만 찾는 탐지기는 그 줄을
  // 못 본다 — 이 검사를 처음 썼을 때 실제로 놓쳤고, 변이 주입이 그것을 잡았다.
  //
  // 반면 `.toISOString()` 자체는 막지 않는다 — 시각까지 들어 있는 전체 ISO 문자열은
  // 시간대가 붙어 있어 모호하지 않다. 거기서 앞 10자만 떼내는 순간 UTC 의
  // 달력을 사용자에게 강요하게 된다. **그 자르는 행위만** 금지한다.
  const UTC_TODAY = /\.toISOString\(\)\s*\.slice\(/

  const listSources = async () => {
    const { promises: fs } = await import('node:fs')
    const out = []
    const walk = async (dir) => {
      for (const e of await fs.readdir(dir, { withFileTypes: true })) {
        const p = `${dir}/${e.name}`
        if (e.isDirectory()) await walk(p)
        else if (/\.tsx?$/.test(e.name)) out.push(p)
      }
    }
    await walk('src')
    return out
  }

  test('검사가 공허하지 않다 — 파일을 찾았고 탐지기가 동작한다', async () => {
    const files = await listSources()
    assert.ok(files.length > 20, `src 아래 .ts/.tsx 를 제대로 못 찾았습니다: ${files.length}개`)
    // 탐지기를 합성 입력으로 증명한다.
    assert.ok(UTC_TODAY.test('new Date().toISOString().slice(0, 10)'),
      '탐지기가 UTC 오늘 계산을 못 잡습니다')
    // ★ 고치기 전에 실제로 있던 바로 그 줄. 수신자가 `new Date()` 가 아니다.
    assert.ok(UTC_TODAY.test('const toISODate = (d: Date) => d.toISOString().slice(0, 10)'),
      '한 단계 건너눠서 자르는 줄을 못 잡습니다(이것이 실제 결함의 모양입니다)')
    assert.ok(!UTC_TODAY.test('new Date(row.created_at).toISOString()'),
      '저장된 시각의 직렬화를 잡으면 오탐입니다')
    assert.ok(!UTC_TODAY.test("new Date().toLocaleDateString('ko-KR')"),
      '날짜 표시 자체를 잡으면 오탐입니다')
    // 주석 제거가 코드를 지우지 않는지 같은 자리에서 본다.
    assert.ok(stripComments("const u = 'https://a.b' // note").includes('https://a.b'),
      '주석 제거가 URL 을 망가뜨립니다')
  })

  test('★ src 어디에도 날짜를 UTC 로 잘라내는 자리가 없다', async () => {
    const { promises: fs } = await import('node:fs')
    const offenders = []
    for (const file of await listSources()) {
      const code = stripComments(await fs.readFile(file, 'utf8'))
      if (UTC_TODAY.test(code)) offenders.push(file)
    }
    assert.deepEqual(
      offenders, [],
      '"오늘"을 UTC 로 만드는 자리가 있습니다(KST 09:00 이전에 하루 당깁니다). '
      + `상세는 src/lib/format.ts 의 ymdPlusDays() 주석: ${offenders.join(', ')}`
    )
  })

  test('검색폼 퀵버튼이 공용 함수를 쓴다', async () => {
    const { promises: fs } = await import('node:fs')
    const form = await fs.readFile('src/app/search/SearchForm.tsx', 'utf8')
    assert.ok(form.includes('todayInDisplayZone()'),
      '매각기일 퀵버튼의 "오늘"이 한국 시각이 아닙니다')
    assert.ok(form.includes('ymdPlusDays('),
      '퀵버튼의 +N일 계산이 공용 함수를 거치지 않습니다')
    // 계약을 고치면서 기능을 잃지 않는다 — 버튼 네 개가 그대로 살아 있는가.
    for (const arg of ['(0)', '(7)', '(14)', '(null)']) {
      assert.ok(form.includes(`setQuickAuctionDate${arg}`), `퀵버튼 ${arg} 이 사라졌습니다`)
    }
  })

  test('공용 함수가 날짜만 다루고, 파서가 한 벌이다', async () => {
    const { promises: fs } = await import('node:fs')
    const lib = await fs.readFile('src/lib/format.ts', 'utf8')
    assert.ok(lib.includes('export function ymdPlusDays'), 'ymdPlusDays 가 없습니다')
    assert.ok(lib.includes('function parseYmdToUtcMs'), 'parseYmdToUtcMs 가 없습니다')
    // daysBetween 이 자기 파서를 다시 들면 규칙이 두 벌이 된다(고치기 전이 그랬다).
    const between = lib.slice(lib.indexOf('function daysBetween'))
    assert.ok(!/const parse = /.test(between.slice(0, 400)),
      'daysBetween 이 자기 파서를 따로 듭니다 — parseYmdToUtcMs 를 쓰십시오')
  })

  test('내보내기 파일명도 같은 기준을 쓴다', async () => {
    const { promises: fs } = await import('node:fs')
    const btn = await fs.readFile('src/app/favorites/ExportButtons.tsx', 'utf8')
    assert.ok(btn.includes('todayInDisplayZone()'), 'CSV 파일명의 날짜가 UTC 입니다')
  })
})


// ================================================================
// 즐겨찾기 토글이 두 화면에서 **같은 규칙**으로 동작한다 — 소스 계약 (2026-09-01 신설)
//
// 이 토글은 두 벌 있다.
//
//     src/app/search/FavoriteButton.tsx        검색 결과 카드의 하트
//     src/app/properties/[id]/page.tsx         상세 화면의 하트
//
// 합치지 않은 이유는 실제로 다른 것이 있기 때문이다 — 로그인 복귀 대상(검색은 쿼리스트링을
// 통째로 보존, 상세는 고정 경로)과, 상세에만 있는 늦은 응답 가드(`idRef`, BUGS #225).
// 카드는 `itemId` 가 prop 이라 그 가드가 필요 없다. 그래서 **데이터의 정본은 하나**
// (`/api/v1/favorites` + 정수 `item_id`)이고, 갈라지는 것은 화면 사정뿐이다.
//
// 문제는 **갈라지면 안 되는 부분을 지키는 것이 주석뿐**이었다는 것이다. 두 파일 모두
// "이미 원하는 상태(중복 등록 / 이미 삭제됨)는 실패가 아니다"를 Error Code 로 구분하는데,
// 한쪽에서 그 분기가 빠지면 사용자는 **성공한 동작에 대해 빨간 문구**를 본다.
// 오류도 로그도 없이 문구만 틀리는, 이 저장소가 반복해 겪은 모양이다.
//
// 값 자체가 서버와 어긋나는 것(`FAVORITE_NOT_FOUND` -> `FAVORITE_NOTFOUND` 같은 오타)은
// `test_schema_hygiene.py` 의 ErrorCode 대조가 잡는다. 여기서는 **두 화면이 같은 규칙을
// 쓰는가**만 본다.
// ================================================================

describe('즐겨찾기 토글이 두 화면에서 같은 규칙을 쓴다 (2026-09-01) — 소스 계약', () => {
  const FILES = ['src/app/search/FavoriteButton.tsx', 'src/app/properties/[id]/page.tsx']
  const read = async (p) => (await import('node:fs')).promises.readFile(p, 'utf8')

  test('검사가 공허하지 않다 — 두 파일을 실제로 읽었고 토글이 들어 있다', async () => {
    for (const f of FILES) {
      const code = await read(f)
      assert.ok(code.length > 1000, `${f} 를 제대로 읽지 못했습니다 (${code.length}자)`)
      assert.ok(code.includes('handleToggleFavorite'),
        `${f} 에 즐겨찾기 토글이 없습니다 — 파일이 옮겨졌다면 이 목록을 고치십시오`)
    }
  })

  test('★ 두 화면이 같은 엔드포인트와 같은 식별자를 쓴다 (정본이 하나다)', async () => {
    for (const f of FILES) {
      const code = await read(f)
      assert.ok(/postJSON<[^>]*>\('\/api\/v1\/favorites'/.test(code),
        `${f} 의 등록이 /api/v1/favorites 가 아닙니다`)
      assert.ok(/deleteJSON<[^>]*>\(`\/api\/v1\/favorites\/\$\{/.test(code),
        `${f} 의 해제가 /api/v1/favorites/{id} 가 아닙니다`)
      assert.ok(/\{\s*item_id:/.test(code),
        `${f} 가 item_id 말고 다른 이름으로 물건을 지목합니다`)
    }
  })

  test('★ 두 화면 모두 "이미 원하는 상태"를 실패로 보지 않는다', async () => {
    for (const f of FILES) {
      const code = await read(f)
      assert.ok(code.includes('ERROR_CODES.FAVORITE_NOT_FOUND'),
        `${f} 가 이미 삭제된 관심물건을 실패로 표시합니다`)
      assert.ok(code.includes('ERROR_CODES.FAVORITE_ALREADY_EXISTS'),
        `${f} 가 이미 등록된 관심물건을 실패로 표시합니다`)
    }
  })

  test('분기를 문구가 아니라 Error Code 로 한다', async () => {
    for (const f of FILES) {
      const code = await read(f)
      // 코드 값을 문자열로 직접 적으면 상수와 갈라진다 — 반드시 ERROR_CODES 를 거친다.
      const literal = code.match(/'FAVORITE_[A-Z_]+'/g) || []
      assert.deepEqual(literal, [],
        `${f} 가 Error Code 를 문자열로 적었습니다(상수를 쓰십시오): ${literal.join(', ')}`)
      assert.ok(/ERROR_CODES/.test(code) && /from '@\/lib\/api'/.test(code),
        `${f} 가 공용 Error Code 상수를 import 하지 않습니다`)
      // message 로 분기하면 문구가 바뀌는 순간 조용히 깨진다.
      assert.ok(!/result\.message\s*===/.test(code),
        `${f} 가 사용자 문구로 분기합니다`)
    }
  })

  test('실패했을 때 하트를 뒤집지 않는다 (아이콘과 에러가 모순되지 않는다)', async () => {
    for (const f of FILES) {
      const code = await read(f)
      // setFavorited(true/false) 는 성공 판정 블록 안에서만 나온다 — 그 판정문이
      // 사라지면 서버가 거절해도 하트가 뒤집힌다.
      assert.ok(/if \(result\.success \|\| result\.error === ERROR_CODES\.FAVORITE_NOT_FOUND\)/.test(code),
        `${f} 의 해제가 서버 판정 없이 상태를 바꿉니다`)
      assert.ok(/if \(result\.success \|\| result\.error === ERROR_CODES\.FAVORITE_ALREADY_EXISTS\)/.test(code),
        `${f} 의 등록이 서버 판정 없이 상태를 바꿉니다`)
    }
  })

  test('로그인 만료(401/403)를 두 화면이 똑같이 다룬다', async () => {
    for (const f of FILES) {
      const code = await read(f)
      assert.ok(/err\.status === 401 \|\| err\.status === 403/.test(code),
        `${f} 가 만료된 세션을 구분하지 않습니다`)
      assert.ok(code.includes('로그인이 만료되었습니다'),
        `${f} 의 만료 안내 문구가 다릅니다`)
    }
  })

  test('재진입 가드가 양쪽에 있다 (연타로 중복 요청이 나가지 않는다)', async () => {
    for (const f of FILES) {
      const code = await read(f)
      assert.ok(/if \(favBusy/.test(code), `${f} 에 연타 가드가 없습니다`)
      assert.ok(code.includes('setFavBusy(true)'), `${f} 가 busy 를 세우지 않습니다`)
    }
  })
})


// ================================================================
// 로그인 복귀 파라미터 이름이 한 벌인가 — 소스 계약 (2026-09-01 신설)
//
// 복귀 흐름은 **생산자 10곳 / 소비자 2곳**으로 갈라져 있다.
//
//     생산자  src/proxy.ts (서버 게이트) + 클라이언트 9곳
//             (favorites / favorites/import / mypage / properties/recent /
//              properties/[id] / search/FavoriteButton / search/SearchPresets)
//     소비자  src/app/login/page.tsx (hidden input) -> login/actions.ts
//
// 기존 계약 검사는 **소비자 쪽만** 고정하고 있었다(§3.4). 그런데 생산자 하나가
// 파라미터 이름을 바꾸면(`?next=` 같은) `formData.get('redirect')` 는 조용히 null 이
// 되고, `sanitizeRedirectPath(null)` 이 기본값 '/' 을 돌려준다 — **오류 없이 첫 화면**
// 으로 보내진다. 사용자는 보던 물건으로 못 돌아오는데 어디에도 실패가 남지 않는다.
// §3.4 가 막으려던 바로 그 회귀를, 아직 아무도 안 보던 쪽에서 재현할 수 있었다.
//
// 이름을 세 벌 네 벌로 두지 않는다는 것만 본다 — 복귀 **대상**은 화면마다 다른 것이
// 맞다(검색은 쿼리스트링 보존, 검색조건 저장은 입력 중이던 이름까지, 상세는 고정 경로).
// ================================================================

describe('로그인 복귀 파라미터 이름이 한 벌이다 (2026-09-01) — 소스 계약', () => {
  const listSources = async () => {
    const { promises: fs } = await import('node:fs')
    const out = []
    const walk = async (dir) => {
      for (const e of await fs.readdir(dir, { withFileTypes: true })) {
        const p = `${dir}/${e.name}`
        if (e.isDirectory()) await walk(p)
        else if (/\.tsx?$/.test(e.name)) out.push(p)
      }
    }
    await walk('src')
    return out
  }

  // `/login?...` 로 보내는 자리. 쿼리 없는 `/login` 링크(헤더)는 대상이 아니다.
  const LOGIN_NAV = /\/login\?/

  test('검사가 공허하지 않다 — 생산자를 실제로 찾았다', async () => {
    const { promises: fs } = await import('node:fs')
    let producers = 0
    for (const f of await listSources()) {
      const code = await fs.readFile(f, 'utf8')
      if (LOGIN_NAV.test(code)) producers++
    }
    assert.ok(producers >= 6, `로그인 복귀 생산자를 제대로 못 찾았습니다: ${producers}개`)
  })

  test('★ 모든 생산자가 `redirect` 라는 이름을 쓴다', async () => {
    const { promises: fs } = await import('node:fs')
    const offenders = []
    for (const f of await listSources()) {
      const code = await fs.readFile(f, 'utf8')
      for (const line of code.split('\n')) {
        if (!LOGIN_NAV.test(line)) continue
        // 같은 줄에 `redirect` 가 있으면 된다 — `?redirect=` 도,
        // `new URLSearchParams({ redirect: target })` 도 여기서 걸러진다.
        if (/\bredirect\b/.test(line)) continue
        // 미리 만든 변수를 넘기는 형태는 그 변수의 정의를 아래 검사가 본다.
        if (/loginParams/.test(line)) continue
        offenders.push(`${f}: ${line.trim().slice(0, 90)}`)
      }
    }
    assert.deepEqual(offenders, [],
      `로그인 복귀 파라미터 이름이 다른 자리가 있습니다(복귀가 조용히 '/' 로 떨어집니다):\n  ${offenders.join('\n  ')}`)
  })

  test('★ URLSearchParams 로 만드는 쪽도 키가 `redirect` 다', async () => {
    const { promises: fs } = await import('node:fs')
    const built = ['src/app/properties/[id]/page.tsx',
                   'src/app/search/FavoriteButton.tsx',
                   'src/app/search/SearchPresets.tsx']
    for (const f of built) {
      const code = await fs.readFile(f, 'utf8')
      // 두 형태가 실제로 쓰인다 — 생성자 인자로 넣거나 set() 으로 붙이거나.
      assert.ok(/URLSearchParams\(\s*\{[^}]*\bredirect\b\s*:/.test(code)
                || /\.set\(\s*'redirect'\s*,/.test(code),
        `${f} 가 복귀 대상을 'redirect' 키로 싣지 않습니다`)
    }
  })

  test('서버 게이트와 소비자가 같은 이름을 쓴다', async () => {
    const { promises: fs } = await import('node:fs')
    const proxy = await fs.readFile('src/proxy.ts', 'utf8')
    assert.ok(/searchParams\.set\('redirect'/.test(proxy),
      'proxy.ts 가 redirect 파라미터를 붙이지 않습니다')
    const page = await fs.readFile('src/app/login/page.tsx', 'utf8')
    assert.ok(/searchParams\.get\('redirect'\)/.test(page),
      '로그인 화면이 redirect 파라미터를 읽지 않습니다')
    assert.ok(/name="redirect"/.test(page),
      '로그인 폼이 redirect 를 hidden input 으로 싣지 않습니다')
    const actions = await fs.readFile('src/app/login/actions.ts', 'utf8')
    assert.ok(/formData\.get\('redirect'\)/.test(actions),
      'loginAction 이 redirect 를 읽지 않습니다')
  })
})
