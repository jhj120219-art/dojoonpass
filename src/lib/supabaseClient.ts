// ================================================================
// 브라우저(클라이언트 컴포넌트)용 Supabase 연결 파일
// 사용 위치: 'use client' 선언된 컴포넌트에서 import해서 사용
// ================================================================

// 2026-09-03 성능 감사 — `@supabase/ssr`을 **정적 import 하지 않는다**.
//
// 왜: 이 파일을 정적으로 import 하는 클라이언트 컴포넌트가 SiteHeader 하나뿐이어도,
// SiteHeader는 8개 화면 전부가 쓰는 공통 헤더라 supabase-js 전체(realtime/storage/
// postgrest/functions 포함)가 **모든 라우트의 초기 번들**에 들어갔다.
// 실측(production build, `.next/static/chunks`): 그 청크가 242.9KB raw / 64.3KB gzip 이고
// `/search` 초기 JS 227.0KB gzip(nomodule 폴리필 제외) 중 28% 를 혼자 차지했다.
// 로그인하지 않은 첫 방문자도, 404 화면도 예외 없이 받아 갔다.
//
// 그런데 이 라이브러리를 쓰는 코드는 **한 곳도 렌더 중에 부르지 않는다** — 전부
// `useEffect` 안이거나 클릭 핸들러 안이다(호출 지점 12곳 전수 확인). 즉 hydration 을
// 막을 이유가 없다. 그래서 호출 시점에 `import()`로 가져오고, 만들어진 클라이언트를
// 모듈 수준에서 캐시한다.
//
// 동작은 바뀌지 않는다: `createBrowserClient`는 브라우저에서 이미 싱글턴이라
// (node_modules/@supabase/ssr `cachedBrowserClient`) 매번 부르든 캐시하든 같은 인스턴스다.
// 달라지는 것은 **반환값이 Promise 라는 점 하나**이고, 호출부는 모두 async 함수 안이라
// `await` 한 줄만 붙는다.
import type { SupabaseClient } from '@supabase/supabase-js'

// `createBrowserClient`가 돌려주는 타입 그대로다(오버로드 함수라 `ReturnType<>`으로는
// 제네릭이 풀리지 않아 호출부 콜백이 암묵적 any가 된다 — 실제 타입을 직접 쓴다).
type BrowserClient = SupabaseClient

let clientPromise: Promise<BrowserClient> | null = null

export function createClient(): Promise<BrowserClient> {
  if (!clientPromise) {
    clientPromise = import('@supabase/ssr')
      .then(({ createBrowserClient }) =>
        createBrowserClient(
          process.env.NEXT_PUBLIC_SUPABASE_URL!,
          process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
        )
      )
      .catch((err) => {
        // 청크 로드 실패(네트워크 끊김 등)를 영구 캐시하지 않는다 — 다음 시도에서
        // 다시 받아올 수 있어야 한다. 실패 자체는 호출부로 그대로 전달한다.
        clientPromise = null
        throw err
      })
  }
  return clientPromise
}
