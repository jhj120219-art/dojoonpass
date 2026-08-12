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

// ================================================================
// Sprint 49 — "200이면 통과"를 넘어 **실제 결과 데이터**까지 검증한다.
//
// 기존 검사는 정렬/페이지 파라미터를 붙여도 200인지, 로그인으로 튕기지 않는지까지만
// 봤다. 그래서 "정렬 버튼을 눌러도 결과 순서가 그대로"인 결함(SortBar의 기본 sort_order가
// 백엔드 기본값과 달라 첫 클릭이 현재 정렬과 같은 값을 보내던 문제)이 29검사를 전부
// 통과한 채로 남아 있었다. 아래는 그 공백을 메운다.
// ================================================================

// React SSR은 인접한 텍스트 노드 사이에 `<!-- -->`를 넣는다("매각기일<!-- --> <!-- -->↓").
// 문구 단언은 이 마커를 걷어낸 뒤에 해야 한다.
function plain(html) {
  return html.replace(/<!-- -->/g, '')
}

// 결과 카드 링크에 실린 `ids=` 값이 곧 **그 페이지의 물건 id 순서**다(ResultList가
// data.items 순서 그대로 join한다). 렌더된 결과 순서를 HTML에서 직접 읽는 가장 안정적인 지점.
function renderedIdOrder(html) {
  const m = html.match(/\?ids=([^"&]+)&(?:amp;)?i=/)
  return m ? decodeURIComponent(m[1]) : null
}

describe('정렬이 실제 결과 순서를 바꾼다 (Sprint 49)', () => {
  test('같은 조건에서 asc와 desc의 결과 순서가 다르다', async () => {
    // full_address(소재지)는 값이 서로 달라 동점으로 인해 순서가 같아지는 일이 없다.
    const asc = renderedIdOrder((await getText('/?sort_by=full_address&sort_order=asc')).body)
    const desc = renderedIdOrder((await getText('/?sort_by=full_address&sort_order=desc')).body)
    if (asc === null && desc === null) return // 결과 0건인 DB 상태 — 검증 대상 없음
    assert.ok(asc && desc, '정렬 결과에서 물건 목록을 읽지 못했습니다')
    assert.notEqual(asc, desc, 'asc와 desc의 결과 순서가 같습니다 — 정렬이 실제로 적용되지 않습니다')
  })

  test('정렬 표시(화살표)가 백엔드 기본 정렬과 일치한다', async () => {
    // api/v1/search.py의 기본값은 sort_order="desc"이고 sort_by가 없으면
    // `auction_date DESC`다. 프론트가 ↑(asc)로 표시하면 화면이 데이터와 다른 말을 하고,
    // 첫 클릭이 이미 적용 중인 정렬과 같은 값을 보내 "눌러도 안 바뀌는 버튼"이 된다.
    assert.ok(
      plain(homeHtml).includes('매각기일 ↓'),
      '첫 화면 정렬 표시가 백엔드 기본값(desc)과 다릅니다'
    )
    const { body } = await getText('/?sort_order=asc')
    assert.ok(plain(body).includes('매각기일 ↑'), 'sort_order=asc가 표시에 반영되지 않았습니다')
  })

})

describe('기술부채 정리 (Sprint 52)', () => {
  test('결과 카드에 항상 비어 있던 "조회수 -"가 없다', () => {
    // `auction_item`에 조회수 컬럼이 없어 **구조적으로 항상 "-"** 인 죽은 UI였다.
    // 값이 생길 여지가 있는 빈 칸이 아니라 채워질 수 없는 자리라 제거했다.
    assert.ok(
      !homeHtml.includes('조회수'),
      '결과 카드에 조회수 자리가 남아 있습니다 — 채워질 수 없는 값입니다'
    )
  })

  test('수집일(crawl_date) 정렬이 UI에 노출된다', async () => {
    // 백엔드 SORT_COLUMNS와 프론트 타입은 8개를 지원하는데 UI만 7개를 노출해,
    // crawl_date는 URL을 직접 편집해야만 쓸 수 있는 도달 불가 정렬이었다.
    assert.ok(plain(homeHtml).includes('수집일'), '수집일 정렬 버튼이 없습니다')
    const { res, body } = await getText('/?sort_by=crawl_date&sort_order=desc')
    assert.equal(res.status, 200, 'crawl_date 정렬이 거부됐습니다')
    assert.ok(plain(body).includes('수집일 ↓'), '수집일 정렬 상태가 표시되지 않습니다')
    // 실제로 순서가 바뀌는지 — 200만 보고 통과시키지 않는다.
    //
    // 2026-08-12 Sprint 61 정정: 기본 검색 결과(D7 진행 중 물건)에는 `include_closed`를
    // 함께 걸어야 한다. 크롤이 2026-08-01 이후 멈춰 있어(BUGS #46) **아직 기일이 남은
    // 물건 14건이 전부 같은 crawl_date**가 됐고, 정렬 키가 상수인 집합에서는 asc/desc가
    // 같은 순서(= id tie-break)로 나오는 것이 **올바른 동작**이다. 그 상태에서 이 검사가
    // 실패하는 것은 제품 결함이 아니라 검사 설계 결함이었다(정렬 자체는 전체 집합에서
    // 정상 동작함을 실측 확인: asc 2026-07-06 / desc 2026-08-01).
    //
    // 그래서 `include_closed=true`로 **crawl_date가 실제로 여러 값인 집합**을 대상으로
    // 검증한다. 이 집합은 오늘 날짜에 좌우되지 않아 시간이 지나도 무효가 되지 않는다.
    const q = 'sort_by=crawl_date&include_closed=true'
    const asc = renderedIdOrder((await getText(`/?${q}&sort_order=asc`)).body)
    const desc = renderedIdOrder((await getText(`/?${q}&sort_order=desc`)).body)
    if (asc && desc) {
      assert.notEqual(asc, desc, 'crawl_date asc/desc의 결과 순서가 같습니다')
    }
  })



  test('preset_name 파라미터가 검색 결과를 바꾸지 않는다', async () => {
    // 무시되는 파라미터여야 한다 — 결과 건수가 달라지면 검색조건으로 새어 들어간 것이다.
    const plainIds = renderedIdOrder((await getText('/')).body)
    const withName = renderedIdOrder((await getText('/?preset_name=%ED%85%8C%EC%8A%A4%ED%8A%B8')).body)
    assert.equal(withName, plainIds, 'preset_name이 검색 결과에 영향을 줬습니다')
  })
})

describe('페이지 이동이 실제로 다른 물건을 보여준다 (Sprint 49)', () => {
  test('1페이지와 2페이지의 물건 목록이 겹치지 않는다', async () => {
    const p1 = renderedIdOrder((await getText('/?size=20&page=1')).body)
    const p2 = renderedIdOrder((await getText('/?size=20&page=2')).body)
    if (!p1 || !p2) return // 2페이지가 존재하지 않는 DB 상태 — 검증 대상 없음
    const set1 = new Set(p1.split(','))
    const overlap = p2.split(',').filter((id) => set1.has(id))
    assert.equal(overlap.length, 0, `1페이지와 2페이지에 같은 물건이 있습니다: ${overlap.join(',')}`)
  })

  test('size를 바꾸면 한 페이지에 실리는 물건 수가 실제로 달라진다', async () => {
    const small = renderedIdOrder((await getText('/?size=20&page=1')).body)
    const large = renderedIdOrder((await getText('/?size=100&page=1')).body)
    if (!small || !large) return
    assert.ok(
      large.split(',').length >= small.split(',').length,
      'size=100이 size=20보다 적은 물건을 반환했습니다'
    )
  })
})

describe('페이지 범위 초과 처리 (Sprint 49)', () => {
  // 기본 필터가 `auction_date >= 오늘`이라 결과 건수는 매일 줄어든다 — 어제 유효했던
  // 북마크 `?page=3`이 오늘은 범위 밖이 될 수 있다. 실제로 도달하는 상태다.
  const OVER = '/?page=9999'

  test('결과가 있는데 페이지만 범위를 벗어나면 "결과 없음"으로 오인시키지 않는다', async () => {
    const { res, body } = await getText(OVER)
    assert.equal(res.status, 200)
    if (!body.includes('이 페이지에는 표시할 물건이 없습니다')) {
      // 조건에 맞는 물건이 0건인 DB 상태라면 원래의 Empty State가 맞다.
      assert.ok(body.includes('검색 결과가 없습니다'), '빈 페이지에 아무 안내도 없습니다')
      return
    }
    assert.ok(
      !body.includes('검색조건을 줄이거나'),
      '페이지 범위 초과인데 "검색조건을 줄이세요"라는 틀린 안내를 합니다'
    )
  })

  test('복구 동선이 검색조건을 유지한 채 1페이지로 보낸다', async () => {
    const { body } = await getText('/?sort_by=fail_count&sort_order=desc&page=9999')
    if (!body.includes('이 페이지에는 표시할 물건이 없습니다')) return
    const m = body.match(/href="([^"]*)"[^>]*>검색조건 유지하고 1페이지로 이동/)
    assert.ok(m, '복구 링크를 찾지 못했습니다')
    const href = m[1].replace(/&amp;/g, '&')
    const url = new URL(href, BASE)
    assert.equal(url.pathname, '/', '복구 링크가 현재 화면을 벗어납니다')
    assert.equal(url.searchParams.get('sort_by'), 'fail_count', '복구 링크가 검색조건을 버렸습니다')
    assert.equal(url.searchParams.get('page'), null, '복구 링크에 page가 남아 있습니다')
  })
})

describe('잘못된 검색 파라미터 처리 (Sprint 51)', () => {
  // 백엔드는 `size` 1~100, `page` >= 1, sort_by/sort_order 화이트리스트를 400/422로 거부한다.
  // 예전에는 이 경우에도 "검색 결과를 불러오지 못했습니다"(=서버 장애처럼 보이는 문구)만 뜨고
  // 되돌아갈 동선이 전혀 없었다. 북마크·공유 URL에서 실제로 도달하는 상태다.
  const BAD = ['?size=500', '?size=abc', '?page=0', '?page=-5', '?sort_by=DROP', '?sort_order=sideways']

  test('원인을 특정해 안내하고 서버 장애 문구를 쓰지 않는다', async () => {
    for (const qs of BAD) {
      const { res, body } = await getText(`/${qs}`)
      assert.equal(res.status, 200, `${qs}: 화면 자체가 실패했습니다`)
      assert.ok(
        body.includes('검색조건에 잘못된 값이 있습니다'),
        `${qs}: 잘못된 파라미터 전용 안내가 없습니다`
      )
      assert.ok(
        !body.includes('검색 결과를 불러오지 못했습니다'),
        `${qs}: 파라미터 오류인데 서버 장애 문구가 나옵니다`
      )
      assert.ok(body.includes('시/도 전체'), `${qs}: 검색 Form이 사라졌습니다`)
    }
  })

  test('복구 링크가 현재 화면(basePath)을 유지한다', async () => {
    for (const [path, expected] of [['/', '/'], ['/search', '/search']]) {
      const { body } = await getText(`${path}?size=500`)
      const m = body.match(/href="([^"]*)"[^>]*>검색조건 초기화/)
      assert.ok(m, `${path}: 복구 링크가 없습니다`)
      assert.equal(
        new URL(m[1].replace(/&amp;/g, '&'), BASE).pathname,
        expected,
        `${path}: 복구 링크가 사용자를 다른 화면으로 옮깁니다`
      )
    }
  })

  test('정상 요청에는 파라미터 오류 안내가 나오지 않는다', () => {
    assert.ok(
      !homeHtml.includes('검색조건에 잘못된 값이 있습니다'),
      '정상 화면에 파라미터 오류 안내가 떴습니다'
    )
  })
})

describe('검색조건이 실제 결과 데이터에 반영된다 (Sprint 49)', () => {
  test('지역 조건이 결과 카드의 주소에 실제로 반영된다', async () => {
    // 어떤 값이 데이터에 있는지 미리 알 수 없으므로, 첫 화면 결과에서 실제 시/도 하나를
    // 뽑아 그 조건으로 다시 검색한다(고정 건수·고정 지역명에 의존하지 않는다).
    const sidoMatch = homeHtml.match(/(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)[가-힣]*도?\s/)
    if (!sidoMatch) return
    const { body } = await getText('/?sido=%EA%B2%BD%EA%B8%B0')
    if (body.includes('검색 결과가 없습니다')) return
    // 결과 카드의 주소 줄에 "경기"가 들어있어야 한다 — 200만 보고 통과시키지 않는다.
    const addressCells = [...body.matchAll(/class="text-xs text-gray-400 line-clamp-2 break-all">([^<]*)</g)].map((m) => m[1])
    assert.ok(addressCells.length > 0, '결과 카드의 주소를 읽지 못했습니다')
    const wrong = addressCells.filter((a) => a && a !== '-' && !a.includes('경기'))
    assert.equal(wrong.length, 0, `경기 조건인데 다른 지역이 섞여 있습니다: ${wrong.slice(0, 3).join(' / ')}`)
  })

  test('결과가 없는 조건과 있는 조건이 서로 다른 화면을 만든다', async () => {
    const hit = (await getText('/')).body
    const miss = (await getText('/?dong=%EC%A1%B4%EC%9E%AC%ED%95%98%EC%A7%80%EC%95%8A%EB%8A%94%EB%8F%99')).body
    assert.ok(!hit.includes('검색 결과가 없습니다'), '조건 없는 첫 화면이 0건입니다')
    assert.ok(miss.includes('검색 결과가 없습니다'), '존재하지 않는 조건이 결과를 반환했습니다')
  })
})

describe('비로그인 개인화 액션 노출 정책 (MASTER_SPEC §8.2)', () => {
  // "비로그인 상태에서도 즐겨찾기 버튼과 검색조건 저장 UI는 보인다. 누르는 시점에만
  //  로그인으로 유도한다" — 숨기는 회귀가 생기면 여기서 잡힌다.
  test('비로그인 첫 화면에도 검색조건 저장 UI가 보인다', () => {
    assert.ok(homeHtml.includes('검색조건 저장'), '검색조건 저장 UI가 숨겨졌습니다')
    assert.ok(homeHtml.includes('placeholder="검색조건 이름"'), '검색조건 이름 입력칸이 없습니다')
    // 세션 확인 전에는 안내 문구를 그리지 않는다(깜빡임 방지) — 서버 HTML에는 없고
    // hydration 이후에 나타나므로, 문구 자체는 소스에서 사라지지 않았는지로 고정한다.
    return import('node:fs').then(async ({ promises: fs }) => {
      const src = await fs.readFile('src/app/search/SearchPresets.tsx', 'utf8')
      assert.ok(
        src.includes('로그인하면 검색조건을 저장하고 불러올 수 있습니다'),
        '비로그인 안내 문구가 사라졌습니다'
      )
      assert.ok(
        /redirectToLogin\(\)/.test(src),
        '비로그인 상태에서 저장을 눌렀을 때 로그인으로 유도하지 않습니다'
      )
    })
  })

  test('비로그인 첫 화면에도 즐겨찾기 버튼이 보인다', () => {
    if (!homeHtml.includes('/properties/')) return // 결과 0건 상태
    assert.ok(
      homeHtml.includes('aria-label="즐겨찾기 추가"'),
      '비로그인 결과 카드에 즐겨찾기 버튼이 없습니다'
    )
  })
})

describe('서버 인증 게이트의 위치와 규약 (Sprint 50)', () => {
  // Next.js 16이 `middleware` 파일 규약을 deprecate하고 `proxy`를 권장한다.
  // Sprint 50에서 `src/middleware.ts` → `src/proxy.ts`로 전환했다(로직 무변경).
  // 두 파일이 동시에 존재하면 Next가 빌드를 **실패**시키므로 그 상태를 테스트로 막는다.


})

describe('마이페이지 (Sprint 54)', () => {
  // 새 화면 스펙을 만들지 않고 기존 사용자 API 3개를 조합한 조회 전용 화면이다.
  // 여기서 고정하는 것은 **도달 가능성과 인증 경계** — 화면 구성/디자인은 단언하지 않는다.
  test('`/mypage`는 개인화 화면이라 서버에서 인증을 요구한다', async () => {
    const res = await get('/mypage')
    assert.ok(
      res.status === 307 || res.status === 302,
      `/mypage가 비로그인에 열립니다 (status ${res.status})`
    )
    const loc = new URL(res.headers.get('location'), BASE)
    assert.equal(loc.pathname, '/login')
    assert.equal(loc.searchParams.get('redirect'), '/mypage', '복귀 경로가 보존되지 않았습니다')
  })

  test('비로그인 상태에서도 Navigation에 마이페이지가 노출된다', () => {
    // §7.2 — 개인화 메뉴는 숨기지 않고, 누르는 시점에 로그인으로 유도한다.
    assert.ok(homeHtml.includes('마이페이지'), 'Header에 마이페이지 메뉴가 없습니다')
    assert.ok(homeHtml.includes('/mypage'), '마이페이지 링크가 없습니다')
  })
})

describe('레거시 라우트 정리 (Sprint 51)', () => {
  // `/properties`는 Supabase 시드 5행을 그리면서 링크는 FastAPI `auction_item` id로 보내
  // **404도 없이 전혀 다른 물건이 열리던** 화면이었다(`docs/BUGS.md` #34).
  // 검색 첫 화면(`/`)이 같은 목적을 정확한 데이터로 수행하므로 `/`로 영구 이동시켰다.
  test('`/properties`는 검색 첫 화면으로 보낸다', async () => {
    const res = await get('/properties')
    assert.ok(
      res.status === 307 || res.status === 308 || res.status === 302,
      `/properties가 여전히 자체 화면을 렌더합니다 (status ${res.status})`
    )
    const loc = new URL(res.headers.get('location'), BASE)
    // 비로그인이면 proxy 게이트가 먼저 /login으로 보내고, 로그인 상태면 /로 간다.
    // 어느 쪽이든 **레거시 목록 화면을 그리지 않는 것**이 이 계약의 핵심이다.
    assert.ok(
      loc.pathname === '/' || loc.pathname === '/login',
      `/properties가 예상 밖의 경로로 보냅니다: ${loc.pathname}`
    )
  })

  test('`/properties` 하위 경로는 영향받지 않는다', async () => {
    // 상세와 최근조회는 여전히 로그인 게이트(307 -> /login)여야 한다.
    for (const path of ['/properties/84', '/properties/recent']) {
      const res = await get(path)
      assert.ok(
        res.status === 307 || res.status === 302,
        `${path}가 게이트되지 않습니다 (status ${res.status})`
      )
      const loc = new URL(res.headers.get('location'), BASE)
      assert.equal(loc.pathname, '/login', `${path}가 로그인이 아닌 곳으로 보냅니다`)
      assert.equal(
        loc.searchParams.get('redirect'),
        path,
        `${path}의 복귀 경로가 레거시 redirect에 먹혔습니다`
      )
    }
  })

})

describe('로그인 성공 후 복귀 계약 (MASTER_SPEC §3.4)', () => {
  // 실제 자격증명 제출은 이 스위트의 범위 밖이다(설계 원칙 4). 다만 "성공 시 어디로
  // 보내는가"는 서버 액션 소스에 고정할 수 있고, 그것이 이 계약의 핵심이다.

})
