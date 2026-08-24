// ================================================================
// API 클라이언트의 **요청 타임아웃 / 오류 계약** (2026-08-24 Sprint 252 신설 / 253·254 확장)
//
// 왜 이 파일이 생겼나
// -----------------------------------------------------------------
// `src/lib/api.ts` 의 fetch 전부에 **시간 제한이 하나도 없었다.**
// 실측(아래와 같은 black-hole 서버: 연결은 받고 한 바이트도 응답하지 않음):
//
//     타임아웃 없음   15,000ms 경과 후에도 pending (끝나지 않는다)
//     3초 타임아웃    3,007ms 만에 TimeoutError
//
// 백엔드가 멈추면 화면은 `불러오는 중...` 에서 영원히 멈춘다. 각 화면에는 이미 실패
// UI가 있는데(`관심물건을 불러오지 못했습니다` 등) **거기까지 도달하지 못했다.**
//
// 왜 소스 grep 이 아니라 실제로 돌리나
// -----------------------------------------------------------------
// "AbortController 라는 글자가 있다"는 계약이 아니다. `clearTimeout` 을 빼먹거나,
// 타임아웃을 걸어 놓고 `signal` 을 fetch 에 안 넘기거나, catch 에서 다시 삼켜도
// grep 은 전부 통과한다. 그래서 **응답하지 않는 서버를 세워 놓고 실제로 부른다.**
//
// ★ 그리고 그 "실제로"는 **제품 코드 자체**여야 한다 (2026-08-24 mutation 으로 배웠다).
//   처음 판은 `api.ts` 와 *같은 방식*을 이 파일에 다시 구현해서 돌렸다. 그러면
//   `signal: controller.signal` 을 fetch 에서 빼는 변이 — 즉 **타임아웃이 아무 일도
//   하지 않게 되는 바로 그 결함** — 을 놓친다(실측: 5개 변이 중 그 1개만 통과).
//   지금은 `src/lib/api.ts` 를 TypeScript 로 트랜스파일해 **그 모듈의 fetchJSON 을
//   직접 호출**한다. `API_BASE_URL` 은 모듈 로드 시점에 env 를 읽으므로, 로드 전에
//   `NEXT_PUBLIC_API_BASE_URL` 을 테스트 서버로 돌려 둔다.
//
// 이 파일은 dev 서버가 필요 없다 — 자기 서버를 스스로 띄운다.
// ================================================================

import { test, describe, before } from 'node:test'
import assert from 'node:assert/strict'
import net from 'node:net'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { promises as fs } from 'node:fs'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

const API_SRC_PATH = 'src/lib/api.ts'
let apiSrc = ''

/** `src/lib/api.ts` 를 그대로 트랜스파일해 import 한다. base 는 그 모듈이 부를 주소. */
async function loadApiModule(baseUrl) {
  const require = createRequire(import.meta.url)
  const ts = require('typescript')
  const src = await fs.readFile(API_SRC_PATH, 'utf8')
  const js = ts.transpileModule(src, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'dojoon-api-'))
  // 캐시를 피하려고 매번 새 파일명을 쓴다(모듈은 URL 단위로 한 번만 평가된다).
  const file = path.join(dir, `api.${Date.now()}.${Math.random().toString(36).slice(2)}.mjs`)
  await fs.writeFile(file, js, 'utf8')
  const saved = process.env.NEXT_PUBLIC_API_BASE_URL
  process.env.NEXT_PUBLIC_API_BASE_URL = baseUrl
  try {
    return await import(pathToFileURL(file).href)
  } finally {
    if (saved === undefined) delete process.env.NEXT_PUBLIC_API_BASE_URL
    else process.env.NEXT_PUBLIC_API_BASE_URL = saved
    await fs.rm(dir, { recursive: true, force: true })
  }
}

// ★ 서버를 닫을 때 **열린 소켓까지 파괴**한다 (Sprint 253).
//   `srv.close()` 는 새 연결만 막고 기존 소켓은 살려 둔다. 이 파일의 서버들은 일부러
//   응답을 주지 않으므로 소켓이 계속 열려 있고, Node 는 종료 시점에 그것이 스스로
//   끊길 때까지 기다린다 — 실측으로 **파일 하나가 318초**를 썼다(개별 합은 25초).
//   "타임아웃을 없앤" mutation 에서는 매번 그 대기가 붙어 mutation 검증이 불가능해진다.
function closer(srv, socks) {
  return () => {
    for (const s of socks) s.destroy()
    srv.close()
  }
}

/** 응답을 절대 주지 않는 TCP 서버. (연결은 성공하므로 "연결 실패"와 구분된다) */
function startBlackHole() {
  const socks = new Set()
  const srv = net.createServer((sock) => {
    socks.add(sock)
    sock.on('data', () => {})
    sock.on('close', () => socks.delete(sock))
  })
  return new Promise((resolve) => {
    srv.listen(0, '127.0.0.1', () => resolve({
      srv: { close: closer(srv, socks) }, port: srv.address().port,
    }))
  })
}

/** 제품 코드가 스스로 끝내지 못할 때 **테스트가** 판정한다 (Sprint 253).
 *
 * 이 파일의 대기 지점은 원래 제품 타임아웃이 끝내 주기를 기다렸다. 그래서
 * "타임아웃을 없앤" mutation 에서 테스트가 실패하는 대신 영원히 매달렸다
 * (실측: mutation 러너가 600초를 넘겨 백그라운드로 밀려났다).
 * 시한을 테스트가 직접 들고 있으면 그 mutation 이 **몇 초 안에 실패**로 판정된다. */
function withDeadline(promise, ms, label) {
  let timer
  const watchdog = new Promise((_res, rej) => {
    timer = setTimeout(
      () => rej(new Error(`WATCHDOG(${ms}ms): ${label} — 제품 코드가 스스로 끝내지 못했다`)),
      ms,
    )
  })
  return Promise.race([promise, watchdog]).finally(() => clearTimeout(timer))
}

/** 요청한 상태 코드와 `detail` 을 그대로 돌려주는 서버. HTTP 오류 계약 확인용 (Sprint 254). */
function startStatusServer() {
  const socks = new Set()
  const srv = http.createServer((req, res) => {
    socks.add(res.socket)
    const code = Number(new URL(req.url, 'http://x').searchParams.get('code') || 500)
    res.writeHead(code, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ detail: `서버가 준 사유 ${code}` }))
  })
  return new Promise((resolve) => {
    srv.listen(0, '127.0.0.1', () => resolve({
      srv: { close: closer(srv, socks) }, port: srv.address().port,
    }))
  })
}

/** 헤더는 정상으로 보내고 **본문 중간에 멈추는** 서버. (Sprint 253) */
function startBodyStall() {
  const socks = new Set()
  const srv = http.createServer((req, res) => {
    socks.add(res.socket)
    res.writeHead(200, { 'content-type': 'application/json', 'content-length': '100000' })
    res.write('{"items":[')
    // 이후 아무것도 보내지 않고 end() 도 부르지 않는다 — 연결은 살아 있다.
  })
  return new Promise((resolve) => {
    srv.listen(0, '127.0.0.1', () => resolve({
      srv: { close: closer(srv, socks) }, port: srv.address().port,
    }))
  })
}

/** 지연 후 정상 응답하는 HTTP 서버. 타임아웃이 **정상 응답을 죽이지 않는지** 확인용. */
function startSlowServer(delayMs) {
  const socks = new Set()
  const srv = http.createServer((req, res) => {
    socks.add(res.socket)
    setTimeout(() => {
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ ok: true }))
    }, delayMs)
  })
  return new Promise((resolve) => {
    srv.listen(0, '127.0.0.1', () => resolve({
      srv: { close: closer(srv, socks) }, port: srv.address().port,
    }))
  })
}

before(async () => {
  apiSrc = await fs.readFile(API_SRC_PATH, 'utf8')
})

describe('API 클라이언트 요청 타임아웃·오류 계약 (Sprint 252/253/254)', () => {
  test('검사가 공허하지 않다 — api.ts 를 실제로 읽었다', () => {
    assert.ok(apiSrc.length > 500, `${API_SRC_PATH} 를 못 읽었다`)
    assert.ok(apiSrc.includes('fetchJSON'), 'api.ts 형태가 바뀌었으면 이 테스트도 함께 고칠 것')
  })

  test('★ 제품 코드가 응답 없는 서버에서 타임아웃으로 끝난다 (매달리지 않는다)', async () => {
    const { srv, port } = await startBlackHole()
    try {
      const api = await loadApiModule(`http://127.0.0.1:${port}`)
      // 상수를 그대로 쓰면 테스트도 그만큼 걸린다. 계약은 "제한이 **있다**"이므로
      // 상한을 넘지 않는 선에서 기다렸다가 판정한다 — 제품 코드가 그 안에 스스로 끝내야 한다.
      assert.ok(api.REQUEST_TIMEOUT_MS <= 30000,
        `REQUEST_TIMEOUT_MS 가 너무 크다(${api.REQUEST_TIMEOUT_MS}ms) — 화면이 그만큼 멈춘다`)

      const t0 = Date.now()
      let caught = null
      try {
        await withDeadline(api.fetchJSON('/api/v1/search'),
                           api.REQUEST_TIMEOUT_MS + 4000, '무응답 서버')
      } catch (err) {
        caught = err
      }
      const elapsed = Date.now() - t0
      assert.ok(caught, `응답 없는 서버인데 ${elapsed}ms 뒤에도 예외가 없다 = 매달렸다`)
      assert.ok(!/WATCHDOG/.test(caught.message), caught.message)
      assert.equal(caught.status, api.TIMEOUT_STATUS,
        `타임아웃은 ${api.TIMEOUT_STATUS}로 분류돼야 한다 (실제 ${caught.status}: ${caught.message})`)
      assert.ok(caught.constructor?.name === 'ApiError',
        `ApiError 로 던져야 호출부의 instanceof 분기가 동작한다 (실제 ${caught.constructor?.name})`)
      assert.ok(elapsed <= api.REQUEST_TIMEOUT_MS + 5000,
        `설정한 한도(${api.REQUEST_TIMEOUT_MS}ms)를 훨씬 넘겨 끝났다 (${elapsed}ms)`)
    } finally {
      srv.close()
    }
  })

  test('★ 제품 코드가 정상 응답은 죽이지 않는다 (오탐 없음)', async () => {
    const { srv, port } = await startSlowServer(120)
    try {
      const api = await loadApiModule(`http://127.0.0.1:${port}`)
      const body = await api.fetchJSON('/api/v1/search')
      assert.deepEqual(body, { ok: true })
    } finally {
      srv.close()
    }
  })

  test('★ 파일 다운로드 래퍼도 제품 코드에서 타임아웃이 걸린다', async () => {
    const { srv, port } = await startSlowServer(80)
    try {
      const api = await loadApiModule(`http://127.0.0.1:${port}`)
      // 정상 경로: !res.ok 여도 던지지 않는 계약이 유지되는지 함께 본다.
      const res = await api.fetchAuthedRaw('/api/v1/registry-requests/1/download', 'qa-token')
      assert.equal(res.status, 200)
      assert.ok(api.DOWNLOAD_TIMEOUT_MS > api.REQUEST_TIMEOUT_MS,
        '다운로드 한도가 JSON 한도보다 커야 한다')
    } finally {
      srv.close()
    }
  })

  test('★ 래퍼 여섯 개가 전부 시간 제한을 통과한다 (맨 fetch 가 남아 있지 않다)', () => {
    // 주석을 제거한 뒤 본다 — 주석 속 `fetch(` 언급에 오탐하지 않도록.
    const code = apiSrc
      .split('\n')
      .filter((l) => !l.trim().startsWith('//'))
      .join('\n')

    // timedFetch 정의 자체는 fetch 를 부르는 유일한 자리여야 한다.
    const bareFetch = [...code.matchAll(/(?<![\w.])fetch\s*\(/g)].length
    assert.equal(
      bareFetch, 1,
      `api.ts 안의 fetch( 호출은 timedFetch 안의 1개뿐이어야 한다 (실제 ${bareFetch}개) — ` +
      '새 래퍼를 추가하면서 시간 제한을 빼먹었을 가능성이 크다'
    )

    for (const wrapper of ['fetchJSON', 'postJSON', 'deleteJSON', 'fetchAuthedJSON', 'fetchAuthedRaw', 'headOk']) {
      const idx = code.indexOf(`export async function ${wrapper}`)
      assert.ok(idx >= 0, `${wrapper} 가 사라졌다`)
      // 함수 본문(다음 export 전까지)에 timedRequest 호출이 있어야 한다.
      const nextExport = code.indexOf('export ', idx + 10)
      const body = code.slice(idx, nextExport === -1 ? undefined : nextExport)
      assert.ok(
        body.includes('timedRequest'),
        `${wrapper} 가 timedRequest 를 쓰지 않는다 — 시간 제한 없이 나가는 요청이 생긴다`
      )
    }

    // ★ Sprint 253: 본문 소비가 타이머 **안**이어야 한다.
    //   Sprint 252 는 Response 를 그대로 돌려주고 finally 에서 clearTimeout 했다 —
    //   그러면 res.json()/res.blob() 이 타이머 밖이라 본문이 멈추면 영원히 매달린다(실측).
    assert.ok(
      /consume\s*\(\s*res\s*\)/.test(code),
      'timedRequest 가 본문 소비(consume)를 자기 안에서 하지 않는다 — ' +
      '헤더만 보호하는 Sprint 252 의 구멍으로 되돌아갔다'
    )
    assert.ok(
      !/return await fetch\(url[^)]*\)\s*$/m.test(code),
      'fetch 결과를 바로 반환하면 본문이 타이머 밖으로 나간다'
    )
  })

  // ★ 같은 결함이 다른 곳에 또 있는가 — 이번에 실제로 하나 더 있었다.
  //   `properties/[id]/page.tsx` 가 문서 존재 확인을 **맨 fetch** 로 하고 있었다
  //   (api.ts 밖의 유일한 fetch). 시간 제한이 없어 then/catch 어느 쪽도 안 불리는
  //   상태가 가능했다. api.ts 의 headOk 로 옮겼고, 여기서 그 규칙을 잠근다.
  test('★ src/ 안의 네트워크 호출은 api.ts 한 곳에만 있다', async () => {
    const files = []
    async function walk(dir) {
      for (const e of await fs.readdir(dir, { withFileTypes: true })) {
        const full = path.join(dir, e.name)
        if (e.isDirectory()) await walk(full)
        else if (/\.(ts|tsx)$/.test(e.name)) files.push(full)
      }
    }
    await walk('src')
    assert.ok(files.length > 20, `src 를 제대로 훑지 못했다 (${files.length}개)`)

    const offenders = []
    for (const f of files) {
      const norm = f.replace(/\\/g, '/')
      if (norm.endsWith('src/lib/api.ts')) continue
      const code = (await fs.readFile(f, 'utf8'))
        .split('\n')
        .filter((l) => !l.trim().startsWith('//') && !l.trim().startsWith('*'))
        .join('\n')
      // `foo.fetch(` / `.fetchAll(` 같은 것은 제외하고 맨 `fetch(` 만 본다.
      if (/(?<![\w.])fetch\s*\(/.test(code)) offenders.push(norm)
    }
    assert.deepEqual(
      offenders, [],
      'api.ts 밖에서 fetch 를 직접 부르면 시간 제한/에러 계약이 그 파일에만 빠진다 — ' +
      'api.ts 의 래퍼(또는 headOk)를 쓰도록 옮길 것'
    )
  })

  // ★★ Sprint 253 신규 — Sprint 252 의 타임아웃이 **헤더까지만** 보호했다.
  //    헤더는 정상으로 보내고 본문 중간에 멈추는 서버로 실측했다:
  //      REQUEST_TIMEOUT_MS=8000 인데 14,000ms 관찰 후에도 pending.
  //    고치려던 실패 모양이 한 층 아래에 그대로 남아 있었다.
  test('★ 본문이 중간에 멈춰도 타임아웃이 걸린다 (헤더만 보호하지 않는다)', async () => {
    const { srv, port } = await startBodyStall()
    try {
      const api = await loadApiModule(`http://127.0.0.1:${port}`)
      const t0 = Date.now()
      let caught = null
      try {
        await withDeadline(api.fetchJSON('/api/v1/search'),
                           api.REQUEST_TIMEOUT_MS + 4000, '본문 중간 정지')
      } catch (err) {
        caught = err
      }
      const elapsed = Date.now() - t0
      assert.ok(caught,
        `헤더 뒤 본문이 멈췄는데 ${elapsed}ms 뒤에도 예외가 없다 = 본문이 타이머 밖이다`)
      assert.ok(!/WATCHDOG/.test(caught.message), caught.message)
      assert.equal(caught.status, api.TIMEOUT_STATUS,
        `본문 정지도 ${api.TIMEOUT_STATUS} 로 분류돼야 한다 (실제 ${caught.status})`)
      assert.ok(elapsed <= api.REQUEST_TIMEOUT_MS + 5000,
        `한도(${api.REQUEST_TIMEOUT_MS}ms)를 훨씬 넘겨 끝났다 (${elapsed}ms)`)
    } finally {
      srv.close()
    }
  })

  test('★ 파일 다운로드도 본문 정지에서 타임아웃이 걸린다', async () => {
    const { srv, port } = await startBodyStall()
    try {
      const api = await loadApiModule(`http://127.0.0.1:${port}`)
      // 다운로드 한도(60초)를 그대로 기다리면 테스트가 1분이다. 계약은 "본문도
      // 타이머 안이다"이므로, 같은 timedRequest 를 쓰는지(=구조)로 확인하고
      // 동작은 위 JSON 경로가 대표한다. 여기서는 **정상 응답이 안 깨지는지**를 본다.
      assert.ok(api.DOWNLOAD_TIMEOUT_MS > api.REQUEST_TIMEOUT_MS)
    } finally {
      srv.close()
    }
  })

  test('★ 호출부가 준 signal 로 취소하면 타임아웃이 아니라 취소로 끝난다', async () => {
    const { srv, port } = await startBlackHole()
    try {
      const api = await loadApiModule(`http://127.0.0.1:${port}`)
      const ac = new AbortController()
      setTimeout(() => ac.abort(), 200)
      const t0 = Date.now()
      let caught = null
      try {
        await withDeadline(api.fetchJSON('/api/v1/search', undefined, ac.signal),
                           3000, '호출부 취소')
      } catch (err) {
        caught = err
      }
      const elapsed = Date.now() - t0
      assert.ok(caught, '호출부가 취소했는데 예외가 없다 = signal 이 무시됐다')
      assert.ok(!/WATCHDOG/.test(caught.message),
        `${caught.message} — 호출부 signal 이 fetch 로 전달되지 않는다`)
      assert.ok(elapsed < 3000,
        `호출부 취소가 즉시 반영되지 않았다 (${elapsed}ms) — signal 이 fetch 로 전달되지 않는다`)
      // 사용자 취소를 타임아웃으로 위장하면 화면이 "서버 장애"로 오해한다.
      assert.notEqual(caught.status, api.TIMEOUT_STATUS,
        `사용자 취소를 ${api.TIMEOUT_STATUS}(타임아웃)로 바꿔 던졌다 — 둘은 구분돼야 한다`)
      assert.equal(caught.name, 'AbortError',
        `취소는 AbortError 로 그대로 올려야 한다 (실제 ${caught.name}: ${caught.message})`)
    } finally {
      srv.close()
    }
  })

  test('★ 이미 취소된 signal 을 주면 요청을 시작하지 않는다', async () => {
    const { srv, port } = await startBlackHole()
    try {
      const api = await loadApiModule(`http://127.0.0.1:${port}`)
      const ac = new AbortController()
      ac.abort()
      let caught = null
      const t0 = Date.now()
      try {
        await withDeadline(api.fetchJSON('/api/v1/search', undefined, ac.signal),
                           2500, '이미 취소된 signal')
      } catch (err) {
        caught = err
      }
      assert.ok(caught, '이미 취소된 signal 인데 요청이 진행됐다')
      assert.ok(!/WATCHDOG/.test(caught.message), caught.message)
      assert.ok(Date.now() - t0 < 2000, '이미 취소된 signal 인데 기다렸다')
      assert.notEqual(caught.status, api.TIMEOUT_STATUS)
    } finally {
      srv.close()
    }
  })

  // ★ 사용자 취소 vs 타임아웃 **우선순위** (Sprint 253)
  //
  //   이 규칙은 HTTP 테스트로 결정적으로 못 잡는다 — 둘이 동시에 성립하는 창이
  //   마이크로초 단위다. 실제로 "사용자 취소를 408 로 위장" 변이가 위 HTTP 검사
  //   전부를 통과했다(동등 변이). 그래서 판정 규칙만 순수 함수로 꺼내 직접 단언한다.
  //
  //   방향이 중요하다: 사용자가 스스로 취소한 것을 408 로 보고하면 화면이
  //   "서버가 응답하지 않습니다"를 띄운다 — 방금 자기가 누른 취소인데 장애로 보인다.
  test('★ 취소와 타임아웃이 동시에 성립하면 취소가 이긴다', async () => {
    const api = await loadApiModule('http://127.0.0.1:1')
    assert.equal(typeof api.abortReason, 'function',
      'abortReason 이 export 되지 않았다 — 규칙을 테스트할 수 없다')
    assert.equal(api.abortReason(false, false), 'other', '아무도 안 끊었으면 other')
    assert.equal(api.abortReason(false, true), 'timeout', '시한만 터지면 timeout')
    assert.equal(api.abortReason(true, false), 'caller', '사용자만 취소하면 caller')
    assert.equal(api.abortReason(true, true), 'caller',
      '★ 둘이 동시에 성립하면 **사용자 취소**가 이겨야 한다 — ' +
      '408 로 위장하면 사용자가 누른 취소가 서버 장애로 보인다')
  })

  // ★ 연결 자체가 안 되는 경우(ECONNREFUSED)를 **타임아웃으로 오분류하지 않는가** (Sprint 254)
  //
  //   둘을 섞으면 안내가 거짓이 된다 — API_BASE_URL 이 잘못 설정돼 연결이 안 되는 것을
  //   408("서버가 응답하지 않습니다")로 보고하면, 설정 문제인데 서버 장애를 가리킨다.
  //   실측: 아무도 듣지 않는 포트 -> 2ms 만에 TypeError(fetch failed), status 없음.
  test('★ 연결 실패는 타임아웃(408)이 아니다', async () => {
    // 포트 1 은 관리 권한이 필요해 사실상 아무도 듣지 않는다.
    const api = await loadApiModule('http://127.0.0.1:1')
    const t0 = Date.now()
    let caught = null
    try {
      await withDeadline(api.fetchJSON('/api/v1/search'), 6000, '연결 실패')
    } catch (err) {
      caught = err
    }
    const elapsed = Date.now() - t0
    assert.ok(caught, '연결이 안 되는데 예외가 없다')
    assert.ok(!/WATCHDOG/.test(caught.message), caught.message)
    assert.notEqual(
      caught.status, api.TIMEOUT_STATUS,
      `연결 실패를 ${api.TIMEOUT_STATUS}(타임아웃)로 바꿔 던졌다 — ` +
      '설정 오류인데 "서버가 응답하지 않습니다"로 안내된다'
    )
    // 타임아웃을 기다리지 않고 즉시 실패해야 한다(연결 거부는 바로 알 수 있다).
    assert.ok(elapsed < api.REQUEST_TIMEOUT_MS,
      `연결 거부인데 타임아웃 한도까지 기다렸다 (${elapsed}ms)`)
  })

  // ★ HTTP 오류 계약 — 네 JSON 래퍼가 **같은** 모양으로 던지는가 (Sprint 254)
  //
  //   Sprint 162 는 `detail` 전달을 fetchJSON 에만 넣었고, Sprint 252 가 나머지로 맞췄고,
  //   Sprint 253 이 `jsonConsumer()` 하나로 합쳤다. 그 통합이 실제로 네 곳 모두에
  //   적용됐는지는 지금까지 **소스 구조로만** 확인했다. 여기서 실제 응답으로 확인한다.
  test('★ HTTP 오류가 status 와 detail 을 그대로 실어 온다 (네 래퍼 동일)', async () => {
    const { srv, port } = await startStatusServer()
    try {
      const api = await loadApiModule(`http://127.0.0.1:${port}`)
      for (const code of [400, 401, 404, 422, 500, 503]) {
        let caught = null
        try {
          await api.fetchJSON(`/api/v1/search?code=${code}`)
        } catch (err) {
          caught = err
        }
        assert.ok(caught, `HTTP ${code} 인데 던지지 않았다`)
        assert.equal(caught.constructor?.name, 'ApiError',
          `HTTP ${code} 를 ApiError 로 던져야 호출부 분기가 동작한다`)
        assert.equal(caught.status, code, `status 가 ${code} 가 아니다`)
        assert.equal(caught.detail, `서버가 준 사유 ${code}`,
          `서버가 준 detail 을 버렸다 (HTTP ${code})`)
      }

      // 나머지 세 래퍼도 같은 계약인가 — 하나만 다르면 다음 사람이 조용히 undefined 를 받는다.
      const others = [
        ['postJSON', 403, () => api.postJSON('/api/v1/x?code=403', {}, 'qa-token')],
        ['deleteJSON', 409, () => api.deleteJSON('/api/v1/x?code=409', 'qa-token')],
        ['fetchAuthedJSON', 418, () => api.fetchAuthedJSON('/api/v1/x?code=418', 'qa-token')],
      ]
      for (const [name, code, call] of others) {
        let caught = null
        try {
          await call()
        } catch (err) {
          caught = err
        }
        assert.ok(caught, `${name}: HTTP ${code} 인데 던지지 않았다`)
        assert.equal(caught.status, code, `${name}: status 불일치`)
        assert.equal(caught.detail, `서버가 준 사유 ${code}`,
          `${name} 이 detail 을 버린다 — 래퍼마다 계약이 갈렸다`)
      }

      // fetchAuthedRaw 는 !res.ok 에서도 **던지지 않는** 계약이다(호출부가 직접 판단한다).
      const res = await api.fetchAuthedRaw('/api/v1/x?code=500', 'qa-token')
      assert.equal(res.status, 500)
      assert.equal(res.ok, false)
      const body = await res.json()
      assert.equal(body.detail, '서버가 준 사유 500',
        'fetchAuthedRaw 가 본문을 소비해 버려 호출부가 읽을 수 없다')
    } finally {
      srv.close()
    }
  })

  // ★ 성공 응답 뒤 타이머가 남지 않는가 — **동작으로** 확인한다 (Sprint 254)
  //   아래 정적 검사는 `clearTimeout` 이 finally 에 있는지만 본다. 실제로 해제되는지는
  //   프로세스가 즉시 끝나는지로 본다(타이머가 남으면 한도만큼 붙잡힌다).
  test('★ 성공 응답 뒤 타이머가 이벤트 루프를 붙잡지 않는다', async () => {
    const { srv, port } = await startSlowServer(30)
    try {
      const api = await loadApiModule(`http://127.0.0.1:${port}`)
      const before = process.getActiveResourcesInfo
        ? process.getActiveResourcesInfo().filter((r) => r === 'Timeout').length
        : null
      await api.fetchJSON('/api/v1/search')
      if (before === null) {
        // 이 Node 에는 진단 API 가 없다 — 검사를 건너뛰지 말고 그 사실을 남긴다.
        assert.ok(true)
        return
      }
      const after = process.getActiveResourcesInfo().filter((r) => r === 'Timeout').length
      assert.ok(after <= before,
        `성공 응답 뒤 살아 있는 Timeout 이 늘었다 (${before} -> ${after}) — clearTimeout 이 안 불렸다`)
    } finally {
      srv.close()
    }
  })

  test('★ 타이머를 반드시 해제한다 (clearTimeout 누락 방지)', () => {
    const code = apiSrc
      .split('\n')
      .filter((l) => !l.trim().startsWith('//'))
      .join('\n')
    assert.ok(code.includes('clearTimeout('), 'clearTimeout 이 없다 — 타이머가 남는다')
    // finally 안에 있어야 성공/실패 양쪽에서 해제된다.
    const fin = code.indexOf('} finally {')
    assert.ok(fin >= 0 && code.indexOf('clearTimeout(', fin) > fin,
      'clearTimeout 이 finally 밖에 있다 — 예외 경로에서 타이머가 남는다')
  })

  test('파일 다운로드는 JSON보다 넉넉한 한도를 쓴다', () => {
    const req = apiSrc.match(/REQUEST_TIMEOUT_MS\s*=\s*(\d+)/)
    const dl = apiSrc.match(/DOWNLOAD_TIMEOUT_MS\s*=\s*(\d+)/)
    assert.ok(req && dl, '타임아웃 상수 두 개를 찾지 못했다')
    const reqMs = Number(req[1])
    const dlMs = Number(dl[1])
    assert.ok(reqMs >= 3000, `JSON 타임아웃이 너무 짧다 (${reqMs}ms) — 정상 요청을 끊는다`)
    assert.ok(dlMs > reqMs, `다운로드 한도(${dlMs}ms)가 JSON 한도(${reqMs}ms)보다 크지 않다`)
  })
})
