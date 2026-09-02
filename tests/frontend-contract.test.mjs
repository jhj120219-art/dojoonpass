// ================================================================
// Frontend 계약 테스트 (Sprint 45 신규)
//
// docs/FRONTEND_MASTER_SPEC.md가 "절대 변경 금지"로 못박은 계약을 고정한다.
// Sprint 44에서 손으로 확인했던 흐름이 다음에 조용히 깨지는 것을 막는 것이 목적이다.
//
// 실행:  npm run test:frontend        (Next 서버 + FastAPI 백엔드가 **둘 다** 떠 있어야 함)
//        BASE_URL=http://localhost:3000 API_BASE_URL=http://localhost:8000 npm run test:frontend
//
//   1) python -m uvicorn api_server:app --host 127.0.0.1 --port 8000
//   2) npm run dev      (또는 npm run build && npm run start)
//   3) npm run test:frontend
//
// 백엔드가 빠지면 검색 결과가 0건이 되고, 결과 데이터를 단언하는 검사들이 줄줄이 실패한다.
// 예전에는 그 상황이 "비로그인 결과 카드에 즐겨찾기 버튼이 없습니다"처럼 **원인과 무관한
// 문구**로 보고돼, 백엔드가 안 떠 있다는 사실을 알아채는 데 시간이 걸렸다(2026-08-13
// Sprint 72). 아래 before() 훅이 두 서버를 각각 확인하고 무엇이 빠졌는지 지목한다.
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
import { KNOWN_UNSUPPORTED } from './_search_param_contract.mjs'

const BASE = (process.env.BASE_URL ?? 'http://localhost:3000').replace(/\/$/, '')

// 프런트(서버 컴포넌트)가 직접 호출하는 FastAPI 주소. 기본값은 .env.local의
// NEXT_PUBLIC_API_BASE_URL과 같다 — node --test는 .env를 읽지 않으므로 여기서 기본값을 둔다.
const API_BASE = (process.env.API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

// redirect: 'manual' — 3xx를 따라가지 않고 그대로 관찰해야 게이트 동작을 검증할 수 있다.
async function get(path) {
  return fetch(`${BASE}${path}`, { redirect: 'manual', headers: { 'accept-language': 'ko' } })
}
async function getText(path) {
  const res = await get(path)
  return { res, body: await res.text() }
}

let homeHtml = ''

// 데이터 전제의 판정 결과. before() 가 채우고, 데이터가 꼭 필요한 검사만 이것을 본다.
let dataAvailable = false
let dataDiagnosis = ''
const nlIndent = '\n  '

before(async () => {
  let res
  try {
    res = await get('/')
  } catch (err) {
    assert.fail(
      `Next 서버(${BASE})에 연결할 수 없습니다. 먼저 "npm run dev" 또는 "npm run start"로 띄운 뒤 실행하세요.\n원인: ${err.message}`
    )
  }
  assert.equal(res.status, 200, `첫 화면이 200이 아닙니다 (${res.status})`)
  homeHtml = await res.text()

  // ── 백엔드 사전 점검 ────────────────────────────────────────────────
  // 이 스위트의 상당수는 "200이면 통과"가 아니라 **실제 결과 데이터**를 단언한다
  // (Sprint 49에서 의도적으로 그렇게 바꿨다 — 정렬 버튼을 눌러도 순서가 그대로였던
  // BUGS #29/#30이 200 검사만으로는 전부 통과했기 때문). 그래서 백엔드가 없으면
  // 결과가 0건이 되고 그 검사들이 원인과 무관한 문구로 실패한다.
  //
  // 여기서 한 번 확인해 **무엇이 빠졌는지** 지목한다. 건너뛰지 않고 실패시키는 이유는,
  // 백엔드 없이 통과한 결과를 "게이트 통과"로 오해하면 안 되기 때문이다.
  let apiRes
  try {
    apiRes = await fetch(`${API_BASE}/api/v1/search?size=1`, { cache: 'no-store' })
  } catch (err) {
    assert.fail(
      `FastAPI 백엔드(${API_BASE})에 연결할 수 없습니다.\n` +
        `  python -m uvicorn api_server:app --host 127.0.0.1 --port 8000\n` +
        `으로 띄운 뒤 다시 실행하세요. (다른 주소면 API_BASE_URL 환경변수로 지정)\n` +
        `원인: ${err.message}`
    )
  }
  assert.equal(
    apiRes.status,
    200,
    `백엔드 검색 API가 200이 아닙니다 (${apiRes.status}) — ${API_BASE}/api/v1/search`
  )

  // 물건이 0건인지 확인한다. **여기서 실패시키지는 않는다** (2026-08-20 Sprint 224).
  //
  // ★ 앞 판본은 여기서 assert 로 막았다. before() 훅이 실패하면 node:test 는 **그 아래
  //   전부**를 실패로 떨어뜨린다 — 실측 2026-08-20: 50개 test / 93개 단언이 한꺼번에
  //   빨간불이 됐다. 그런데 그중 데이터를 실제로 보는 것은 **단 하나**였다.
  //   나머지(라우팅·리다이렉트·랜드마크·h1·aria-label·레이아웃·레거시 경로…)는 결과가
  //   0건이어도 전부 판정 가능하다. 즉 데이터가 하루만 낡아도 **접근성/라우팅 계약이
  //   통째로 관측 불능**이 되고 있었고, 화면상으로는 "93건 실패"라 진짜 결함과 구별되지도
  //   않았다. 관측 공백을 결함으로 보고하면 안 되고, 반대로 감춰도 안 된다.
  //
  //   그래서: 전제는 **전용 검사 하나**로 명시적으로 실패시키고(조용한 초록 방지),
  //   데이터가 필요 없는 검사는 **실제로 실행**한다. 데이터가 꼭 필요한 검사만 skip 한다
  //   (skip 은 통과가 아니다 — 판정하지 못했다는 뜻이다).
  const payload = await apiRes.json()
  dataAvailable = typeof payload?.total === 'number' && payload.total > 0

  // "비었다"와 "전부 지났다"는 원인도 조치도 다르다 — 뭉뚱그리지 않는다.
  // 기본 검색은 `auction_date >= 오늘`이므로, include_closed 로 다시 물어 구분한다.
  if (!dataAvailable) {
    try {
      const all = await fetch(`${API_BASE}/api/v1/search?size=1&include_closed=true`, {
        cache: 'no-store',
      })
      const allPayload = await all.json()
      dataDiagnosis =
        allPayload?.total > 0
          ? `DB 에는 물건이 ${allPayload.total}건 있으나 **매각기일이 전부 지났다**` +
            ` — 크롤이 멈춰 있다(수집 파이프라인 확인). DB 가 빈 것이 아니다.`
          : `DB 자체가 비어 있다 (include_closed 로도 0건) — 수집이 한 번도 되지 않았다.`
    } catch (err) {
      dataDiagnosis = `원인을 확인하지 못했다 (include_closed 재조회 실패: ${err.message})`
    }
  }
})

// 이 머신이 **운영 데이터의 주인인가**. 코드로는 알 수 없으므로 선언하게 한다
// (2026-08-25, docs/BUGS.md #200 — 파이썬 쪽 `test_pipeline_integrity.py` §11 과 같은 규약).
//
// DOJOONPASS 는 머신을 역할로 나눈다 — 운영 Daily Crawl 은 데스크탑1이 돌리고,
// 이 저장소로 개발/QA 를 하는 머신은 크롤을 돌리지 않는다. 그 머신에서 "기본 검색 0건"은
// 정상이지 제품 결함이 아니다. 그런데 이 검사는 그 구분 없이 실패로 찍어 왔고,
// 개발 머신에서 **고칠 수 없는 영구 red** 가 됐다.
const DATA_ROLE_ENV = 'DOJOONPASS_DATA_ROLE'
const isOperationalData =
  (process.env[DATA_ROLE_ENV] || '').trim().toLowerCase() === 'operational'

describe('백엔드 데이터 전제 (Sprint 224)', () => {
  // 이 검사 **하나만** 데이터 부족을 보고한다. 아래의 다른 검사들은 그것과 무관하게
  // 각자 판정한다. 빨간불 93개 대신 원인을 정확히 가리키는 빨간불 1개다.
  test('기본 검색에 판정 가능한 물건이 있다 (다른 검사의 전제)', (t) => {
    if (!isOperationalData) {
      // 개발 머신에서는 실패로 만들지 않되 **크게 남긴다** — 선언을 잊은 운영 머신이
      // 이 줄을 보고 알아채도록. 값을 숨기지는 않는다.
      const declared = (process.env[DATA_ROLE_ENV] || '').trim()
      if (declared) {
        console.log(
          `    ** ${DATA_ROLE_ENV}=${JSON.stringify(declared)} 를 인식하지 못했다 **` +
            ` 개발 머신으로 처리한다. 운영으로 선언하려면 정확히 "operational" 이어야 한다.`
        )
      }
      console.log(
        `    [역할 미선언] 이 머신은 운영 데이터의 주인이라고 선언되지 않았다` +
          ` -> 기본 검색 ${dataAvailable ? '정상' : '0건'}을 제품 판정으로 쓰지 않는다.`
      )
      if (!dataAvailable) console.log(`    ${dataDiagnosis}`)
      console.log(
        `    이 머신의 데이터가 운영이라면 ${DATA_ROLE_ENV}=operational 로 선언하라.`
      )
      t.skip('이 머신은 운영 데이터의 주인이 아니다 (DOJOONPASS_DATA_ROLE 미선언)')
      return
    }
    assert.ok(
      dataAvailable,
      `백엔드 기본 검색이 0건이다 — 결과 데이터를 단언하는 검사는 판정할 수 없다.` +
        `${nlIndent}${dataDiagnosis}`
    )
  })
})

// 결과 카드가 실제로 렌더됐는가. 헤더의 `/properties/recent` 링크에 속지 않도록
// **id + ids 컨텍스트**까지 있는 형태만 인정한다.
function hasResultCards(html) {
  return /\/properties\/\d+\?ids=/.test(html)
}

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
  test('결과 카드가 /properties/{id}로 링크하며 목록 컨텍스트를 싣는다', (t) => {
    const m = homeHtml.match(/\/properties\/(\d+)\?ids=([\d,%C]*)&(?:amp;)?i=(\d+)/)
    if (!hasResultCards(homeHtml)) {
      // 결과 0건인 DB 상태에서는 검증할 링크 자체가 없다 — 판정 불가(통과가 아니다).
      t.skip('결과 카드 0개 — 판정 불가. 사유는 "백엔드 데이터 전제" 검사 참고')
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
  // ★ 이 자리에는 원래 "서버가 내려준 HTML에서 name="redirect" hidden input을 정규식으로
  //   찾는" 검사가 있었다. **원리상 통과할 수 없는 검사였다** (2026-08-13 Sprint 98).
  //
  //   `/login`은 `'use client'` + `<Suspense fallback={null}>`이라 서버가 내려주는 HTML은
  //   빈 껍데기이고(빌드 출력에서도 `○ /login` = static), hidden input은 `useSearchParams()`가
  //   도는 **하이드레이션 이후**에 생긴다. 이 파일은 fetch로 받은 HTML 문자열만 보므로
  //   그 값을 볼 수 없다.
  //
  //   왜 아무도 몰랐나 — 이 파일의 검사는 Next/FastAPI가 **둘 다 떠 있어야** 도는데,
  //   서버 없이 실행하면 `before()`가 실패해 전부 취소된다. 그래서 이 실패는 "서버가 없다"에
  //   묻혀 한 번도 드러나지 않았다. 서버를 띄우고 돌려 보고서야 106개 중 유일한 실패로 나왔다.
  //
  //   실제 브라우저에서 하이드레이션 후를 확인한 결과 **제품은 정상**이다 —
  //   `input[name=redirect]`가 type=hidden으로 존재하고 값이 원래 URL과 정확히 일치했다.
  //   따라서 검사를 **없애지 않고 관측 가능한 곳으로 옮겼다**:
  //   폼이 값을 싣는지는 `tests/source-contract.test.mjs`의
  //   "로그인 화면이 redirect 값을 폼에 hidden input으로 싣는다"가 고정한다.
  //
  //   여기서는 HTTP로 **실제로 확인할 수 있는 것**만 남긴다: 로그인 화면이 redirect를 달고도
  //   정상 응답하고, 그 값을 잃어버리거나 외부로 튕기지 않는다는 것.
  test('로그인 화면은 redirect를 달고도 정상 응답하고 값을 잃지 않는다', async () => {
    const target = '/properties/84?ids=84,85,86&i=1'
    const path = `/login?redirect=${encodeURIComponent(target)}`
    const res = await get(path)
    assert.equal(res.status, 200, '로그인 화면이 200이 아닙니다')

    // 서버가 리다이렉트로 값을 깎아먹지 않는지 확인한다(3xx면 location에 값이 남아야 한다).
    const loc = res.headers.get('location')
    if (loc) {
      const to = new URL(loc, BASE)
      assert.equal(to.origin, new URL(BASE).origin, '로그인 화면이 외부로 리다이렉트했습니다')
      assert.equal(
        to.searchParams.get('redirect'),
        target,
        '리다이렉트 과정에서 redirect 값이 유실됐습니다'
      )
    }
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

  // Sprint 162 — 서버가 준 정확한 사유를 그대로 보여 준다.
  //
  // 예전에는 400을 받으면 **응답 본문을 통째로 버리고** 고정 안내만 띄웠다. 그 고정 문구가
  // 하필 "(페이지 번호는 1 이상, 한 페이지 개수는 1~100)"이라 페이지/개수만 언급해서,
  // `sort_by`나 `min_appraisal`이 틀린 사용자는 **엉뚱한 곳을 고치라는 안내**를 받았다.
  // 백엔드는 `{"detail": "허용되지 않는 sort_by 값입니다: BOGUS"}`처럼 정확히 알려 준다.
  test('서버가 사유를 문자열로 주면 그것을 보여 준다', async () => {
    // ★ 필드명만 찾으면 안 된다 — `sort_by`/`min_appraisal` 은 정렬 링크와 검색 Form에도
    //   문자열로 들어 있어 **사유를 버려도 통과한다**(실제로 mutation 이 살아남아서 고쳤다).
    //   서버 문구 자체를 찾고, 동시에 기본 안내가 **사라졌는지**까지 확인한다.
    const cases = [
      ['?sort_by=BOGUS', '허용되지 않는 sort_by 값입니다'],
      ['?min_appraisal=99999999999999999999999', 'min_appraisal 값이 허용 범위를 벗어났습니다'],
    ]
    for (const [qs, serverMessage] of cases) {
      const { res, body } = await getText(`/search${qs}`)
      assert.equal(res.status, 200, `${qs}: 화면 자체가 실패했습니다`)
      assert.ok(
        body.includes('검색조건에 잘못된 값이 있습니다'),
        `${qs}: 잘못된 파라미터 전용 안내가 없습니다`
      )
      assert.ok(
        body.includes(serverMessage),
        `${qs}: 서버가 준 사유("${serverMessage}")가 화면에 없습니다 — 응답 본문이 버려졌습니다`
      )
      // 사유를 보여 줄 때는 페이지/개수만 언급하는 기본 안내가 **대체돼야** 한다.
      // (둘 다 나오면 여전히 엉뚱한 곳을 고치라고 안내하는 셈이다)
      assert.ok(
        !body.includes('주소창의 검색조건 중 일부가 허용되지 않는 값입니다'),
        `${qs}: 정확한 사유가 있는데 페이지/개수 안내가 함께 나옵니다`
      )
      // 사유를 보여 줄 때도 되돌아갈 동선은 남아야 한다.
      assert.ok(body.includes('검색조건 초기화'), `${qs}: 복구 링크가 사라졌습니다`)
    }
  })

  // 사유가 **문자열이 아닐 때**는 기존 안내로 떨어져야 한다.
  // FastAPI 검증 오류(`page=0`, `size=99999`)의 `detail`은 영어 객체 배열이라
  // 사용자에게 보여줄 것이 못 된다. 넓게 보여 주려다 이런 것까지 노출하면 안 된다.
  test('사유가 객체 배열이면 기존 안내로 떨어진다', async () => {
    for (const qs of ['?page=0', '?size=99999']) {
      const { body } = await getText(`/search${qs}`)
      assert.ok(
        body.includes('주소창의 검색조건 중 일부가 허용되지 않는 값입니다'),
        `${qs}: 기본 안내가 없습니다`
      )
      // 내부 표현이 새어 나오면 안 된다.
      for (const bad of ['greater_than_equal', 'less_than_equal', 'Input should be', '"loc"']) {
        assert.ok(!body.includes(bad), `${qs}: 내부 검증 표현 ${bad} 이(가) 노출됐습니다`)
      }
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

  test('결과가 없는 조건과 있는 조건이 서로 다른 화면을 만든다', async (t) => {
    // 이 파일에서 **결과가 실제로 있어야만** 판정되는 유일한 검사다
    // (나머지는 0건 상태를 스스로 처리하거나 데이터를 보지 않는다).
    if (!dataAvailable) {
      t.skip('기본 검색 0건 — 판정 불가(통과가 아니다). 사유는 "백엔드 데이터 전제" 검사 참고')
      return
    }
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

  test('비로그인 첫 화면에도 즐겨찾기 버튼이 보인다', (t) => {
    if (!hasResultCards(homeHtml)) {
      t.skip('결과 카드 0개 — 판정 불가. 사유는 "백엔드 데이터 전제" 검사 참고')
      return
    }
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

describe('예상치 못한 오류/404가 Next 기본 화면이 아니다 (2026-08-22 신설)', () => {
  // src/app/error.tsx / not-found.tsx (Next.js App Router 규약 파일)가 없으면
  // 렌더링 중 예외나 없는 경로 요청에서 사용자가 스타일 없는 Next 기본 화면을 본다.
  // 2026-08-22 실측: 이 저장소 src/app 전체에 이 두 파일이 **0개**였다. 코드/기존 스타일
  // 관례(properties/[id]/page.tsx의 loadError 분기)를 그대로 재사용해 신설했다 - 이
  // 검사는 그 신설이 나중에 조용히 사라지지 않게 잠근다.

  test('존재하지 않는 경로는 커스텀 404를 보여준다(Next 기본 화면이 아니다)', async () => {
    const { res, body } = await getText('/이런-경로는-절대-존재하지-않는다-xyz-2026')
    assert.equal(res.status, 404, `없는 경로가 404가 아닙니다 (${res.status})`)
    assert.ok(
      body.includes('페이지를 찾을 수 없습니다'),
      'not-found.tsx의 문구가 응답에 없습니다 - Next 기본 404로 되돌아간 것으로 보입니다'
    )
    assert.ok(
      !/This page could not be found/.test(body),
      'Next.js 기본 404 문구가 그대로 보입니다 - not-found.tsx가 적용되지 않았습니다'
    )
  })

  test('src/app/error.tsx / not-found.tsx 소스 파일이 실제로 존재한다', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const root = path.join(import.meta.dirname, '..')
    for (const rel of ['src/app/error.tsx', 'src/app/not-found.tsx']) {
      assert.ok(fs.existsSync(path.join(root, rel)), `${rel}가 없습니다`)
    }
    const errorSrc = fs.readFileSync(path.join(root, 'src/app/error.tsx'), 'utf8')
    assert.ok(errorSrc.startsWith("'use client'"), 'error.tsx는 Client Component여야 한다(Next.js 규약)')
    assert.ok(/reset\s*\(\s*\)/.test(errorSrc), 'error.tsx가 reset()을 호출하지 않습니다(다시 시도 불가)')
  })
})

// ================================================================
// 검색 파라미터 계약 — 프런트가 보내는 것을 백엔드가 **실제로 읽는가**
// (2026-08-26 신설, `docs/BUGS.md` #239)
//
// 이 저장소가 같은 함정을 두 번 밟았다.
//
//   BUGS #123  면적 4종을 프런트가 보내는데 백엔드가 읽지 않았다 —
//              "사용자가 면적을 좁혀도 결과가 그대로였다. 오류도 안내도 없다."
//   BUGS #239  면적이 구현된 뒤에도 결합 규칙이 틀려 두 조건을 함께 주면 항상 0건이었다.
//
// FastAPI 는 **모르는 쿼리 파라미터를 조용히 무시한다.** 그래서 프런트가 오타를 내거나
// 아직 없는 필터를 보내도 200 이 돌아오고, 사용자에게는 "그런 물건이 없다"로 보인다.
// 이 검사는 그 침묵을 깨는 것이 목적이다 — OpenAPI 를 진실의 원천으로 삼아
// **프런트가 보내는 이름 전부**가 백엔드에 실재하는지 본다.
//
// 목록을 손으로 적지 않는다(그러면 목록이 코드보다 뒤처진다). 양쪽 다 유도한다:
//   보내는 쪽 = SearchForm.tsx 의 `query.<name> =` 전수
//   받는 쪽   = /openapi.json 의 /api/v1/search 파라미터 전수
// ================================================================
describe('검색 파라미터 계약 — 보내는 것과 읽는 것이 일치한다 (BUGS #239)', () => {
  // 목록은 `tests/_search_param_contract.mjs` 한 곳에만 있다 — source-contract 와 공유한다.
  // (두 벌로 두면 한쪽에서만 빼도 다른 쪽이 계속 눈감아 준다. BUGS #204)
  // 특수조건 UI 를 여는 날 그 목록에서 빼야 하고, 빼지 않으면 아래 "죽은 예외" 검사가 붉어진다.

  async function sentParams() {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile('src/app/search/SearchForm.tsx', 'utf8')
    const code = src.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')
    const names = new Set()
    // 점 표기와 대괄호 표기를 **둘 다** 본다. 점만 보면 `query['min_x'] = ...` 로 바꾸는
    // 순간 검사가 조용히 눈이 먼다(2026-08-26 변이 P4 로 확인한 사각지대).
    for (const m of code.matchAll(/query\.([A-Za-z_][A-Za-z0-9_]*)\s*=/g)) names.add(m[1])
    for (const m of code.matchAll(/query\[\s*['"`]([A-Za-z_][A-Za-z0-9_]*)['"`]\s*\]\s*=/g)) {
      names.add(m[1])
    }
    return names
  }

  async function acceptedParams() {
    const res = await fetch(`${API_BASE}/openapi.json`, { cache: 'no-store' })
    assert.equal(res.status, 200, `openapi.json 을 못 받았습니다 (${res.status})`)
    const spec = await res.json()
    const params = spec.paths?.['/api/v1/search']?.get?.parameters ?? []
    return new Set(params.map((p) => p.name))
  }

  test('검사가 공허하지 않다 — 양쪽 목록을 실제로 얻었다', async () => {
    const sent = await sentParams()
    const accepted = await acceptedParams()
    assert.ok(sent.size >= 15, `보내는 파라미터를 제대로 못 뽑았습니다 (${sent.size}개)`)
    assert.ok(accepted.size >= 15, `OpenAPI 파라미터를 제대로 못 뽑았습니다 (${accepted.size}개)`)
    // 알려진 대표값이 양쪽에 있어야 추출 방식이 살아 있다고 말할 수 있다.
    for (const n of ['min_building_area', 'max_land_area', 'property_type', 'case_no']) {
      assert.ok(sent.has(n), `프런트 추출이 ${n} 를 놓쳤습니다 — 정규식이 낡았습니다`)
      assert.ok(accepted.has(n), `OpenAPI 에 ${n} 가 없습니다`)
    }
  })

  test('★ 프런트가 보내는 파라미터를 백엔드가 전부 받는다 (조용히 무시되는 필터가 없다)', async () => {
    const sent = await sentParams()
    const accepted = await acceptedParams()
    const ignored = [...sent].filter((n) => !accepted.has(n) && !KNOWN_UNSUPPORTED.has(n)).sort()
    assert.deepEqual(
      ignored,
      [],
      `백엔드가 읽지 않는 파라미터를 프런트가 보내고 있습니다 — 사용자는 조건을 좁혔는데 ` +
        `결과가 그대로입니다(BUGS #123 과 같은 형태): ${ignored.join(', ')}`
    )
  })

  test('★ 예외 목록이 코드보다 앞서 나가지 않는다 (죽은 예외 금지)', async () => {
    const sent = await sentParams()
    const accepted = await acceptedParams()
    const stale = [...KNOWN_UNSUPPORTED]
      .filter((n) => accepted.has(n) || !sent.has(n))
      .sort()
    assert.deepEqual(
      stale,
      [],
      `KNOWN_UNSUPPORTED 에 죽은 항목이 있습니다(백엔드가 이미 받거나, 프런트가 더 이상 ` +
        `보내지 않습니다). 예외를 남겨 두면 진짜 결함을 가립니다: ${stale.join(', ')}`
    )
  })

  test('★ 지원하지 않는 파라미터는 실제로 결과를 바꾸지 않는다 (무시됨을 실측)', async () => {
    // "무시된다"를 소스가 아니라 **응답**으로 확인한다.
    const base = await (await fetch(`${API_BASE}/api/v1/search?size=1`, { cache: 'no-store' })).json()
    for (const n of KNOWN_UNSUPPORTED) {
      const res = await fetch(`${API_BASE}/api/v1/search?size=1&${n}=xyz`, { cache: 'no-store' })
      assert.equal(res.status, 200, `${n} 를 붙였더니 200 이 아닙니다 (${res.status})`)
      const got = await res.json()
      assert.equal(
        got.total,
        base.total,
        `${n} 가 결과를 바꿨습니다 — 이미 구현된 것이라면 KNOWN_UNSUPPORTED 에서 빼야 합니다`
      )
    }
  })
})


// ================================================================
// API 응답 ↔ 프런트 타입 대조 (2026-08-31 신설)
//
// ## 왜 생겼나
//
// 이 저장소의 계약 검사는 지금까지 **파라미터 방향**(프런트가 보내는 것 ↔ 백엔드가 받는 것)
// 만 봤다. 반대 방향 — **백엔드가 주는 것 ↔ 프런트가 선언한 것** — 은 아무것도 보지
// 않았고, 실제로 두 번 드리프트가 쌓여 있었다(2026-08-31 실측).
//
//     GET /api/v1/search  items[]     building_area / land_area   2026-08-26 부터 응답에 있음
//     GET /api/v1/item/{id}           sido / sigungu / dong       처음부터 응답에 있음
//                                     building_area / land_area
//
// 타입에 없는 키는 런타임에 아무 문제도 일으키지 않는다. 그래서 **드러나지 않는다.**
// 드러나는 순간은 누군가 "그 데이터는 응답에 없다"고 읽고 **이미 있는 것을 다시 만들 때**다 —
// 검색 카드가 서버 면적을 두고 주소를 다시 파싱하고 있던 것이 정확히 그 결과였다.
//
// ## 무엇을 단언하나
//
//   1. 응답의 모든 키가 타입에 선언돼 있다   (미선언 키 = 위 드리프트)
//   2. 타입에만 있는 키는 optional(`?`) 이다  (없는 것을 있다고 적지 않는다)
//   3. 예외 목록이 코드보다 앞서 나가지 않는다 (죽은 예외 금지)
// ================================================================

describe('API 응답 ↔ 프런트 타입 (2026-08-31)', () => {
  // TS 소스에서 인터페이스의 **최상위 키**를 뽑는다. 중첩 블록은 지우고 본다.
  async function tsKeys(file, name) {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile(file, 'utf8')
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

  async function apiJson(path) {
    const res = await fetch(`${API_BASE}${path}`, { cache: 'no-store' })
    assert.equal(res.status, 200, `${path} 가 200 이 아닙니다 (${res.status})`)
    return res.json()
  }

  // 응답에 있지만 타입에 적지 않기로 **한 것**. 이유 없이 늘리지 않는다.
  //   tenant_rights 는 12컬럼인데 프런트는 9개만 쓴다(`docs/BUGS.md` #254).
  //   좁히는 것은 API 계약 축소라 소비자를 먼저 옮겨야 해서 지금은 그대로 둔다.
  // 임차인 보유 물건을 찾을 때 넘겨 볼 검색 페이지 수(40건/페이지). 찾는 즉시 멈춘다.
const TENANT_SCAN_PAGES = 5

const KNOWN_UNDECLARED = {
    'tenants[]': new Set(['id', 'item_id', 'created_at']),
  }

  function diff(label, apiKeys, ts) {
    const allowed = KNOWN_UNDECLARED[label] ?? new Set()
    const undeclared = [...apiKeys].filter((k) => !ts.all.has(k) && !allowed.has(k)).sort()
    // 타입에만 있는 키는 optional 이어야 한다 — 필수라고 적어 두면 없는 것을 있다고 말한다.
    const phantom = [...ts.required].filter((k) => !apiKeys.has(k)).sort()
    // 죽은 예외: 더 이상 나오지 않는 키를 예외 목록이 붙들고 있으면 1번 검사가 눈감는다.
    const deadAllow = [...allowed].filter((k) => !apiKeys.has(k)).sort()
    return { undeclared, phantom, deadAllow }
  }

  let searchItem = null
  let detail = null

  before(async () => {
    const s = await apiJson('/api/v1/search?size=1&include_closed=true')
    if (s.items && s.items.length) {
      searchItem = s.items[0]
      detail = await apiJson(`/api/v1/item/${searchItem.id}`)
    }
  })

  test('검사가 공허하지 않다 — 실제 응답과 타입을 둘 다 얻었다', async () => {
    assert.ok(searchItem, '검색 응답에 항목이 없어 대조할 수 없습니다(데이터 전제)')
    assert.ok(detail && detail.id, '상세 응답을 얻지 못했습니다')
    const ts = await tsKeys('src/app/search/types.ts', 'SearchResultItem')
    assert.ok(ts.all.size > 10, `타입 키 추출 실패 (${ts.all.size}개)`)
  })

  test('★ GET /api/v1/search items[] 의 모든 키가 타입에 선언돼 있다', async () => {
    const ts = await tsKeys('src/app/search/types.ts', 'SearchResultItem')
    const d = diff('items[]', new Set(Object.keys(searchItem)), ts)
    assert.deepEqual(d.undeclared, [],
      `응답에는 있는데 SearchResultItem 에 없는 키입니다 — "응답에 없다"로 읽혀 같은 데이터를 다시 만들게 됩니다: ${d.undeclared.join(', ')}`)
    assert.deepEqual(d.phantom, [],
      `타입이 필수라고 적었는데 응답에 없는 키입니다: ${d.phantom.join(', ')}`)
  })

  test('★ GET /api/v1/item/{id} 의 모든 키가 타입에 선언돼 있다', async () => {
    const ts = await tsKeys('src/app/properties/[id]/page.tsx', 'AuctionItemDetail')
    const d = diff('item', new Set(Object.keys(detail)), ts)
    assert.deepEqual(d.undeclared, [],
      `응답에는 있는데 AuctionItemDetail 에 없는 키입니다: ${d.undeclared.join(', ')}`)
    assert.deepEqual(d.phantom, [],
      `타입이 필수라고 적었는데 응답에 없는 키입니다: ${d.phantom.join(', ')}`)
  })

  test('상세의 곁딸린 배열도 타입과 맞는다 (documents / images / tenants)', async () => {
    const cases = [
      ['documents', 'src/app/properties/[id]/page.tsx', 'DocumentStatusItem', 'documents[]'],
      ['images', 'src/app/properties/[id]/page.tsx', 'AuctionImage', 'images[]'],
      ['tenants', 'src/app/properties/[id]/rightsAnalysis.ts', 'TenantRow', 'tenants[]'],
    ]
    let checked = 0
    for (const [key, file, name, label] of cases) {
      const rows = detail[key]
      if (!rows || !rows.length) continue      // 이 물건에는 없다 — 다른 물건에서 본다
      checked++
      const ts = await tsKeys(file, name)
      const d = diff(label, new Set(Object.keys(rows[0])), ts)
      assert.deepEqual(d.undeclared, [], `${label}: 타입에 없는 응답 키 ${d.undeclared.join(', ')}`)
      assert.deepEqual(d.phantom, [], `${label}: 응답에 없는 필수 키 ${d.phantom.join(', ')}`)
    }
    // 하나도 못 봤으면 "통과"가 아니라 **못 봤다**고 말한다.
    assert.ok(checked > 0,
      '이 물건에는 documents/images/tenants 가 하나도 없어 곁딸린 배열을 대조하지 못했습니다')
  })

  test('★ 예외 목록이 코드보다 앞서 나가지 않는다 (죽은 예외 금지)', async () => {
    // tenants[] 예외는 그 키들이 **실제로 응답에 실릴 때만** 의미가 있다.
    // 응답에서 사라졌는데 예외가 남으면, 그 키가 다시 생겨도 위 검사가 눈감는다.
    let tenants = detail.tenants
    let scanned = 0
    if (!tenants || !tenants.length) {
      // 임차인 있는 물건을 찾는다(전수 순회는 하지 않는다 — 페이지 예산을 둔다).
      //
      // ★ 2026-09-02: 예전에는 **1페이지 40건만** 봤다. 그 표본에 임차인 보유 물건이
      //   들어 있는 것은 그날 정렬 순서가 정해 주는 **우연**이었다. 실측으로 그 우연이
      //   깨졌다 — 그날 크롤한 282건이 기본 정렬에서 앞으로 오는데 아직 권리분석이
      //   붙지 않아 **1페이지 40건 전부 tenants 가 비었고**(2페이지에 3건 있었다)
      //   이 검사가 붉어졌다. 제품은 멀쩡했고 표본이 얕았던 것뿐이다.
      //   (전체로 보면 물건 2,781건 중 319건(11%)이 임차인을 갖는다.)
      //
      //   그래서 페이지를 넘겨 가며 찾되, 찾는 즉시 멈추고 예산을 넘지 않는다.
      outer:
      for (let page = 1; page <= TENANT_SCAN_PAGES; page++) {
        const s = await apiJson(`/api/v1/search?size=40&include_closed=true&page=${page}`)
        if (!s.items || !s.items.length) break
        for (const it of s.items) {
          scanned++
          const d = await apiJson(`/api/v1/item/${it.id}`)
          if (d.tenants && d.tenants.length) { tenants = d.tenants; break outer }
        }
      }
    }
    assert.ok(tenants && tenants.length,
      `임차인이 있는 물건을 찾지 못해 예외 목록을 검증하지 못했습니다 (물건 ${scanned}건 확인)`)
    const keys = new Set(Object.keys(tenants[0]))
    const dead = [...KNOWN_UNDECLARED['tenants[]']].filter((k) => !keys.has(k)).sort()
    assert.deepEqual(dead, [],
      `응답에 더 이상 없는 키가 예외 목록에 남아 있습니다 — 목록에서 빼십시오: ${dead.join(', ')}`)
  })
})


// ---------------------------------------------------------------------------
// 타입과 응답의 **nullability / 타입** 일치 (2026-09-03, P0-5)
//
// ## 위 검사와 무엇이 다른가
//
// 바로 위 세 검사는 **키 이름**만 본다(선언/미선언/유령). 값이 `number` 인지
// `null` 인지는 아무도 보지 않았다. 그래서 이런 것이 조용히 지나간다:
//
//     TypeScript   appraisal_price: number      // null 이 올 수 없다고 선언
//     실제 응답     "appraisal_price": null      // 그런데 온다
//
// 화면 코드는 선언을 믿고 `price.toLocaleString()` 같은 것을 쓸 수 있고, 그러면
// 그 카드만 런타임에 터진다. 이 저장소가 반복해서 잡아 온 "조용한 오답"의 한 갈래다.
//
// ## 실측으로 확인한 것 (2026-09-03)
//
// 검색 600건 + 상세 305건을 훑어 **위반 0건**이었다. 즉 지금은 맞다. 이 검사는
// 그 상태를 **고정**한다 — DB 컬럼이 `INTEGER DEFAULT 0`(NOT NULL 아님)이라
// 구조적으로는 NULL 이 들어갈 수 있고, 실제로 NULL 을 주입하면 API 가 그대로
// null 을 내보낸다(사본 DB 로 확인). 지금 0건인 것은 데이터가 그럴 뿐이다.
//
// 여러 물건을 표본으로 본다 — 한 건만 보면 그 한 건이 우연히 멀쩡할 수 있다.
// ---------------------------------------------------------------------------
describe('API 응답 ↔ 프런트 타입: nullability/타입 (2026-09-03)', () => {
  // 선언에서 (nullable, 원문타입) 을 뽑는다. 위 tsKeys 와 같은 파서를 쓰되
  // 타입 문자열까지 남긴다.
  async function tsTypes(file, name) {
    const { promises: fs } = await import('node:fs')
    const src = await fs.readFile(file, 'utf8')
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
    const out = new Map()
    for (const line of body.split('\n')) {
      const code = line.split('//')[0].trim()
      const km = /^([a-zA-Z_][a-zA-Z0-9_]*)(\??)\s*:\s*(.+?),?$/.exec(code)
      if (!km) continue
      const declared = km[3].trim().replace(/,$/, '')
      out.set(km[1], {
        nullable: km[2] === '?' || /\bnull\b|\bundefined\b/.test(declared),
        declared,
      })
    }
    return out
  }

  function violations(label, obj, types, id) {
    const bad = []
    for (const [field, spec] of types) {
      if (!(field in obj)) continue          // 키 부재는 위 검사가 본다
      const v = obj[field]
      if (v === null) {
        if (!spec.nullable) bad.push(`${label}.${field} (item ${id}) = null, 선언 ${spec.declared}`)
        continue
      }
      if (/^number(\s*\|\s*null)?$/.test(spec.declared) && typeof v !== 'number') {
        bad.push(`${label}.${field} (item ${id}) = ${typeof v}, 선언 ${spec.declared}`)
      }
      if (/^string(\s*\|\s*null)?$/.test(spec.declared) && typeof v !== 'string') {
        bad.push(`${label}.${field} (item ${id}) = ${typeof v}, 선언 ${spec.declared}`)
      }
      if (/^boolean(\s*\|\s*null)?$/.test(spec.declared) && typeof v !== 'boolean') {
        bad.push(`${label}.${field} (item ${id}) = ${typeof v}, 선언 ${spec.declared}`)
      }
    }
    return bad
  }

  let cards = []
  let details = []

  before(async () => {
    const res = await fetch(`${API_BASE}/api/v1/search?size=40&include_closed=true`,
      { cache: 'no-store' })
    if (res.status === 200) cards = (await res.json()).items ?? []
    for (const c of cards.slice(0, 12)) {
      const r = await fetch(`${API_BASE}/api/v1/item/${c.id}`, { cache: 'no-store' })
      if (r.status === 200) details.push(await r.json())
    }
  })

  test('검사가 공허하지 않다 — 여러 건을 실제로 받았다', () => {
    assert.ok(cards.length >= 10, `검색 표본이 부족합니다 (${cards.length})`)
    assert.ok(details.length >= 5, `상세 표본이 부족합니다 (${details.length})`)
  })

  test('자기 검증 — 선언 위반을 실제로 잡는다', async () => {
    const types = await tsTypes('src/app/search/types.ts', 'SearchResultItem')
    // 일부러 깨뜨린 응답을 넣어 본다. 이것이 통과하면 아래 "0건"은 의미가 없다.
    const broken = { ...cards[0], appraisal_price: null, fail_count: 'many' }
    const bad = violations('items[]', broken, types, 'SELF')
    assert.ok(bad.some((s) => s.includes('appraisal_price')),
      `null 주입을 못 잡았습니다: ${JSON.stringify(bad)}`)
    assert.ok(bad.some((s) => s.includes('fail_count')),
      `타입 불일치를 못 잡았습니다: ${JSON.stringify(bad)}`)
  })

  test('★ 검색 items[] 의 값이 선언한 타입/nullability 와 맞는다', async () => {
    const types = await tsTypes('src/app/search/types.ts', 'SearchResultItem')
    const bad = []
    for (const c of cards) bad.push(...violations('items[]', c, types, c.id))
    assert.deepEqual(bad, [],
      `타입 선언과 실제 응답이 다릅니다 (표본 ${cards.length}건):\n${bad.join('\n')}`)
  })

  test('★ 상세 응답의 값이 선언한 타입/nullability 와 맞는다', async () => {
    const types = await tsTypes('src/app/properties/[id]/page.tsx', 'AuctionItemDetail')
    const bad = []
    for (const d of details) bad.push(...violations('item', d, types, d.id))
    assert.deepEqual(bad, [],
      `타입 선언과 실제 응답이 다릅니다 (표본 ${details.length}건):\n${bad.join('\n')}`)
  })

  test('★ 중첩 블록(case / rights_summary)도 선언과 맞는다', async () => {
    const caseTypes = await tsTypes('src/app/properties/[id]/page.tsx', 'CaseInfo')
    const rightsTypes = await tsTypes('src/app/properties/[id]/page.tsx', 'RightsSummary')
    const bad = []
    let sawCase = 0
    let sawRights = 0
    for (const d of details) {
      if (d.case && typeof d.case === 'object') {
        sawCase++
        bad.push(...violations('case', d.case, caseTypes, d.id))
      }
      if (d.rights_summary && typeof d.rights_summary === 'object') {
        sawRights++
        bad.push(...violations('rights_summary', d.rights_summary, rightsTypes, d.id))
      }
    }
    assert.ok(sawCase >= 1, '중첩 case 블록을 한 건도 보지 못했습니다(검사가 공허합니다)')
    assert.deepEqual(bad, [],
      `중첩 블록의 타입 선언과 실제 응답이 다릅니다 (case ${sawCase} / rights ${sawRights}):\n${bad.join('\n')}`)
  })
})
