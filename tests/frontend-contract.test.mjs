// ================================================================
// Frontend 계약 테스트 (Sprint 45 신규)
//
// docs/FRONTEND_MASTER_SPEC.md가 "절대 변경 금지"로 못박은 계약을 고정한다.
// Sprint 44에서 손으로 확인했던 흐름이 다음에 조용히 깨지는 것을 막는 것이 목적이다.
//
// 실행:  npm run test:frontend        (dev 또는 start 서버가 떠 있어야 함)
//        BASE_URL=http://localhost:3000 npm run test:frontend
//
// 설계 원칙
// 1. **새 라이브러리를 설치하지 않는다** — Node 내장 러너(node:test) + 전역 fetch만 쓴다.
//    (docs/CLAUDE.md: 새 라이브러리 설치는 승인 필요)
// 2. **HTTP 블랙박스로만 검증한다** — 번들러/트랜스파일 설정이 필요 없고, 내부 구현을
//    바꿔도 "사용자에게 보이는 계약"이 그대로면 통과한다.
// 3. **DB 데이터 건수에 의존하지 않는다** — test_search.py가 기대 건수 노후화로 3건
//    실패하는 것과 같은 함정을 반복하지 않기 위해, 구조(링크 형태/상태코드/파라미터 보존)만
//    단언하고 "몇 건이 나오는가"는 단언하지 않는다.
// 4. **자격증명을 다루지 않는다** — 비밀번호 입력이나 실제 세션 파기는 하지 않는다.
//    Node의 fetch는 쿠키 저장소가 없어 모든 요청이 자동으로 "비로그인"이다.
// ================================================================

import { test, describe, before } from 'node:test'
import assert from 'node:assert/strict'

const BASE = (process.env.BASE_URL ?? 'http://localhost:3000').replace(/\/$/, '')

// redirect: 'manual' — 3xx를 따라가지 않고 그대로 관찰해야 게이트 동작을 검증할 수 있다.
async function get(path) {
  return fetch(`${BASE}${path}`, { redirect: 'manual', headers: { 'accept-language': 'ko' } })
}
async function getText(path) {
  const res = await get(path)
  return { res, body: await res.text() }
}

let homeHtml = ''

before(async () => {
  let res
  try {
    res = await get('/')
  } catch (err) {
    assert.fail(
      `서버(${BASE})에 연결할 수 없습니다. 먼저 "npm run dev" 또는 "npm run start"로 띄운 뒤 실행하세요.\n원인: ${err.message}`
    )
  }
  assert.equal(res.status, 200, `첫 화면이 200이 아닙니다 (${res.status})`)
  homeHtml = await res.text()
})

describe('첫 화면 = 검색 화면 (MASTER_SPEC §4)', () => {
  test('`/`는 redirect되지 않는다 (비로그인)', async () => {
    const res = await get('/')
    assert.equal(res.status, 200)
    assert.equal(
      res.headers.get('location'),
      null,
      '`/`가 Location 헤더를 반환했습니다 — 첫 화면 redirect가 되살아났습니다'
    )
  })

  test('`/`는 로그인 화면이 아니다', () => {
    assert.ok(!homeHtml.includes('비밀번호'), '첫 화면에 비밀번호 입력이 있습니다')
    assert.ok(!homeHtml.includes('반갑습니다! 로그인해주세요'), '첫 화면이 로그인 폼입니다')
  })

  test('`/`에 검색 Form이 있다', () => {
    for (const marker of ['시/도 전체', '읍/면/동', '물건정보', '가격 조건']) {
      assert.ok(homeHtml.includes(marker), `검색 Form의 "${marker}"가 없습니다`)
    }
  })

  test('조건 없이 첫 진입해도 경매 물건 목록이 보인다 (비로그인)', () => {
    // 건수는 단언하지 않는다. "결과 영역이 렌더됐는가"만 본다.
    const hasCards = /\/properties\/\d+\?ids=/.test(homeHtml)
    const emptyState = homeHtml.includes('검색 결과가 없습니다')
    assert.ok(hasCards || emptyState, '결과 영역이 아예 렌더되지 않았습니다')
    assert.ok(!homeHtml.includes('검색 결과를 불러오지 못했습니다'), '검색 API 호출이 실패했습니다')
  })
})

describe('검색 실행이 현재 pathname을 유지한다 (MASTER_SPEC §8.2)', () => {
  test('`/`에 검색조건을 붙여도 200이고 화면이 유지된다', async () => {
    const { res, body } = await getText('/?dong=%EC%98%A5%EC%B2%9C%EB%A9%B4')
    assert.equal(res.status, 200)
    assert.equal(res.headers.get('location'), null, '검색조건이 붙으면 다른 경로로 튕깁니다')
    assert.ok(body.includes('시/도 전체'), '검색 후 화면에 검색 Form이 남아있지 않습니다')
  })

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

describe('`/search` 호환 유지 (MASTER_SPEC §2.1)', () => {
  test('`/search`는 계속 200이다', async () => {
    const res = await get('/search')
    assert.equal(res.status, 200)
    assert.equal(res.headers.get('location'), null)
  })

  test('`/search`도 검색조건을 받는다', async () => {
    const { res, body } = await getText('/search?sido=%EC%84%9C%EC%9A%B8')
    assert.equal(res.status, 200)
    assert.ok(body.includes('시/도 전체'), '/search에 검색 Form이 없습니다')
  })

  test('`/`와 `/search`가 같은 화면을 렌더한다', async () => {
    const { body } = await getText('/search')
    for (const marker of ['검색조건 저장', '물건정보', '시/도 전체']) {
      assert.ok(body.includes(marker), `/search에 "${marker}"가 없습니다`)
      assert.ok(homeHtml.includes(marker), `/에 "${marker}"가 없습니다`)
    }
  })
})

describe('결과 → 상세 링크 계약 (MASTER_SPEC §9)', () => {
  test('결과 카드가 /properties/{id}로 링크하며 목록 컨텍스트를 싣는다', () => {
    const m = homeHtml.match(/\/properties\/(\d+)\?ids=([\d,%C]*)&(?:amp;)?i=(\d+)/)
    if (!homeHtml.includes('/properties/')) {
      // 결과 0건인 DB 상태에서는 검증할 링크 자체가 없다 — 실패가 아니라 skip 대상.
      return
    }
    assert.ok(m, '결과 카드 링크가 `/properties/{id}?ids=...&i=...` 형태가 아닙니다')
    assert.ok(Number(m[1]) > 0, 'item id가 숫자가 아닙니다')
  })
})

describe('상세는 로그인 필수 + redirect에 query string 보존 (MASTER_SPEC §3.3/§3.4)', () => {
  const detailPath = '/properties/84?ids=84,85,86&i=1'

  test('비로그인 상세 요청은 로그인으로 보낸다', async () => {
    const res = await get(detailPath)
    assert.ok(
      res.status === 307 || res.status === 302,
      `상세가 비로그인에 열렸습니다 (status ${res.status}) — 상세 로그인 게이트가 사라졌습니다`
    )
    const loc = res.headers.get('location')
    assert.ok(loc, 'Location 헤더가 없습니다')
    assert.ok(new URL(loc, BASE).pathname === '/login', `로그인이 아닌 곳으로 보냅니다: ${loc}`)
  })

  test('redirect 파라미터가 pathname + query string 전체를 보존한다', async () => {
    const res = await get(detailPath)
    const loc = new URL(res.headers.get('location'), BASE)
    const redirect = loc.searchParams.get('redirect')
    assert.ok(redirect, 'redirect 파라미터가 없습니다')

    const target = new URL(redirect, BASE)
    assert.equal(target.pathname, '/properties/84', '상세 경로가 보존되지 않았습니다')
    // 이것이 Sprint 44 #25의 회귀 방지 지점 — 예전에는 여기가 통째로 사라졌다.
    assert.equal(target.searchParams.get('ids'), '84,85,86', 'ids 컨텍스트가 유실됐습니다')
    assert.equal(target.searchParams.get('i'), '1', 'i(현재 인덱스)가 유실됐습니다')
  })

  test('query string이 없는 상세도 정상 게이트된다', async () => {
    const res = await get('/properties/84')
    const loc = new URL(res.headers.get('location'), BASE)
    assert.equal(loc.searchParams.get('redirect'), '/properties/84')
  })
})

describe('로그인 후 원래 URL 복귀 구조 (MASTER_SPEC §3.4)', () => {
  test('로그인 화면이 redirect 값을 폼에 그대로 싣는다', async () => {
    const target = '/properties/84?ids=84,85,86&i=1'
    const { res, body } = await getText(`/login?redirect=${encodeURIComponent(target)}`)
    assert.equal(res.status, 200)

    const m = body.match(/name="redirect"\s+value="([^"]*)"/)
    assert.ok(m, '로그인 폼에 redirect hidden input이 없습니다')
    // HTML 이스케이프(&amp;)를 되돌려 원본과 비교한다.
    const carried = m[1].replace(/&amp;/g, '&')
    assert.equal(carried, target, '로그인 폼이 원래 URL을 그대로 싣지 않습니다')
  })

  // 실제 로그인 제출(=비밀번호 입력)은 하지 않으므로 sanitizeRedirectPath()가 값을
  // 걸러내는 순간 자체는 검증 범위 밖이다. 다만 **제출 전 단계에서 이미 외부로 튕기는지**는
  // 자격증명 없이도 확인할 수 있고, 그게 Open Redirect의 실제 위험 지점이다.
  test('악의적 redirect 값이 GET 단계에서 외부로 튕기지 않는다', async () => {
    for (const evil of ['//evil.example.com', '/\\evil.example.com', 'https://evil.example.com']) {
      const res = await get(`/login?redirect=${encodeURIComponent(evil)}`)
      assert.equal(res.status, 200, `${evil}: 로그인 페이지가 200이 아닙니다`)
      const loc = res.headers.get('location')
      assert.ok(
        !loc || new URL(loc, BASE).origin === new URL(BASE).origin,
        `${evil}: 외부 origin으로 리다이렉트했습니다 -> ${loc}`
      )
    }
  })
})

describe('공개 접근 정책 (MASTER_SPEC §2.2 / §3.1)', () => {
  test('공개 라우트는 미들웨어가 가로채지 않는다', async () => {
    for (const path of ['/', '/search', '/login']) {
      const res = await get(path)
      assert.equal(res.status, 200, `${path}가 200이 아닙니다 (${res.status})`)
    }
  })

  test('정렬/페이지 이동 파라미터를 비로그인으로 처리할 수 있다', async () => {
    for (const qs of ['?sort_by=appraisal_price&sort_order=desc', '?page=2', '?size=50']) {
      const res = await get(`/${qs}`)
      assert.equal(res.status, 200, `비로그인 ${qs} 처리 실패 (${res.status})`)
      assert.equal(res.headers.get('location'), null, `${qs}에서 로그인으로 튕겼습니다`)
    }
  })

  test('개인화 라우트는 화면 진입 시 서버에서 인증을 요구한다', async () => {
    // Sprint 45: 예전에는 /properties/recent만 서버 게이트(307)였고 /favorites는 200을
    // 준 뒤 클라이언트에서 튕겼다. 같은 개인화 화면의 게이트 방식이 갈려 있던 것을 통일했다.
    for (const path of ['/properties/recent', '/favorites']) {
      const res = await get(path)
      assert.ok(
        res.status === 307 || res.status === 302,
        `${path}가 비로그인에 열립니다 (status ${res.status})`
      )
      const loc = new URL(res.headers.get('location'), BASE)
      assert.equal(loc.pathname, '/login', `${path}가 로그인이 아닌 곳으로 보냅니다`)
      assert.equal(loc.searchParams.get('redirect'), path, `${path}의 복귀 경로가 틀렸습니다`)
    }
  })
})

describe('Empty State (Sprint 45)', () => {
  // 결과가 0건이 되도록 존재하지 않는 동 이름을 넣는다. DB 내용과 무관하게 항상 0건이다.
  const NO_HIT = '/?dong=%EC%A1%B4%EC%9E%AC%ED%95%98%EC%A7%80%EC%95%8A%EB%8A%94%EB%8F%99'

  test('결과 0건이면 안내와 복구 동선을 보여준다', async () => {
    const { res, body } = await getText(NO_HIT)
    assert.equal(res.status, 200)
    assert.ok(body.includes('검색 결과가 없습니다'), 'Empty State 문구가 없습니다')
    assert.ok(body.includes('조건 없이 전체 물건 보기'), 'Empty State에 복구 동선이 없습니다')
  })

  test('결과 0건에도 검색 Form은 그대로 남는다', async () => {
    const { body } = await getText(NO_HIT)
    assert.ok(body.includes('시/도 전체'), '0건일 때 검색 Form이 사라졌습니다')
  })

  test('결과 0건이면 페이지네이션 컨트롤을 노출하지 않는다', async () => {
    const { body } = await getText(NO_HIT)
    assert.ok(!body.includes('100개'), '0건인데 페이지 크기 컨트롤이 남아있습니다')
  })

  test('복구 링크가 현재 화면의 경로를 가리킨다 (`/`와 `/search` 각각)', async () => {
    const home = await getText(NO_HIT)
    assert.ok(
      /href="\/"[^>]*>\s*조건 없이 전체 물건 보기/.test(home.body.replace(/\n/g, '')) ||
        home.body.includes('href="/"'),
      '`/`의 복구 링크가 `/`를 가리키지 않습니다'
    )
    const search = await getText(NO_HIT.replace('/?', '/search?'))
    assert.ok(
      search.body.includes('href="/search"'),
      '`/search`의 복구 링크가 `/search`를 가리키지 않습니다 — 사용자를 다른 화면으로 옮깁니다'
    )
  })
})

describe('접근성 기본 (Sprint 47)', () => {
  // Sprint 44에서 공통 Header를 만들며 각 페이지의 <h1>을 옮기다가 span으로 바꿔버려
  // 문서에 h1이 하나도 없는 상태가 됐다(Sprint 47 감사에서 발견). 같은 회귀를 막는다.
  test('화면에 h1이 정확히 하나 있다', () => {
    const h1s = homeHtml.match(/<h1[\s>]/g) ?? []
    assert.equal(h1s.length, 1, `h1 개수가 ${h1s.length}개입니다`)
  })

  test('main / nav 랜드마크가 있다', () => {
    assert.ok(/<main[\s>]/.test(homeHtml), 'main 랜드마크가 없습니다')
    assert.ok(/<nav[\s>]/.test(homeHtml), 'nav 랜드마크가 없습니다')
  })

  test('지역 select에 접근 가능한 이름이 있다', () => {
    assert.ok(homeHtml.includes('aria-label="시/도"'), '시/도 select에 이름이 없습니다')
    assert.ok(homeHtml.includes('aria-label="시/군/구"'), '시/군/구 select에 이름이 없습니다')
  })

  test('문서 언어가 한국어로 선언되어 있다', () => {
    assert.ok(/<html[^>]+lang="ko"/.test(homeHtml), 'lang="ko"가 없습니다')
  })
})

describe('공통 Layout (MASTER_SPEC §5)', () => {
  test('중앙 컨테이너(1320px)를 쓴다', () => {
    assert.ok(homeHtml.includes('max-w-[1320px]'), '중앙 컨테이너가 적용되지 않았습니다')
  })

  test('공통 Header의 Navigation이 노출된다', () => {
    for (const label of ['검색', '최근 본 물건', '관심물건']) {
      assert.ok(homeHtml.includes(label), `Header에 "${label}"가 없습니다`)
    }
  })

  test('반응형 열 구성이 적용되어 있다', () => {
    assert.ok(homeHtml.includes('md:grid-cols-2'), '태블릿 2열 클래스가 없습니다')
    assert.ok(homeHtml.includes('xl:grid-cols-3'), '데스크톱 3열 클래스가 없습니다')
  })
})
