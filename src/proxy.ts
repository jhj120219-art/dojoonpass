// ================================================================
// Next.js Proxy (구 Middleware)
// 목적: 모든 요청마다 세션 자동 갱신 + 비로그인 유저 접근 차단
//
// 2026-08-11 Sprint 50 — `src/middleware.ts`에서 파일 규약만 이전했다.
// Next.js 16이 `middleware` 규약을 deprecate하고 `proxy`를 권장한다
// (빌드 경고: "The 'middleware' file convention is deprecated").
//
// 전환 내용은 **파일명과 export 이름 두 가지뿐**이고 인증 로직은 한 줄도 바뀌지 않았다.
//   - `src/middleware.ts` → `src/proxy.ts`
//   - `export async function middleware()` → `export async function proxy()`
//     (Next의 엔트리 템플릿이 proxy 파일에서는 `mod.proxy`를 먼저 찾는다)
//   - `export const config = { matcher }`는 그대로 동작한다
//     (`isMiddlewareFile()`이 두 규약을 동일하게 취급)
//
// 유일한 실질 변화는 Next가 강제하는 **실행 런타임**이다 — middleware는 Edge 런타임,
// proxy는 항상 Node.js 런타임이다. `@supabase/ssr`의 `createServerClient`와
// `NextResponse`/`request.cookies`는 둘 다에서 동일하게 동작하므로 인증 동작에 영향이 없다.
// (Node 런타임은 Edge의 상위 집합이라 기능이 줄어드는 방향이 아니다.)
// 두 파일이 동시에 존재하면 Next가 빌드를 실패시키므로 `src/middleware.ts`는 삭제했다.
// ================================================================

import { createServerClient } from '@supabase/ssr'
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export async function proxy(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request })

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          )
          supabaseResponse = NextResponse.next({ request })
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          )
        },
      },
    }
  )

  // 세션 갱신 (반드시 호출 필요)
  const { data: { user } } = await supabase.auth.getUser()

  // 보호된 경로: 로그인 안 한 유저는 /login으로 리다이렉트
  //
  // /favorites는 예전에 이 목록에 없어서 **클라이언트에서만** 세션을 확인했다. 그래서
  // /properties/recent(서버 게이트, 307)와 /favorites(200 후 클라이언트 redirect)가 같은
  // 개인화 화면인데도 게이트 방식이 서로 달랐다 — 빈 화면이 잠깐 그려졌다가 튕기고,
  // 인증 경계가 두 곳으로 갈렸다. docs/FRONTEND_MASTER_SPEC.md §3.2가 둘 다 "화면 진입 시"
  // 인증을 요구하므로 서버 게이트로 통일한다.
  // (각 페이지의 클라이언트 체크는 그대로 둔다 — 토큰 만료 등 런타임 상황을 다루는 이중 방어)
  // /mypage는 2026-08-11 Sprint 54에 추가. 개인화 화면은 전부 서버 게이트로 통일한다
  // (§3.2가 '화면 진입 시' 인증을 요구하는 대상들).
  const PROTECTED_PREFIXES = ['/properties', '/favorites', '/mypage']
  const isProtectedPath = PROTECTED_PREFIXES.some((prefix) =>
    request.nextUrl.pathname.startsWith(prefix)
  )

  if (isProtectedPath && !user) {
    const loginUrl = new URL('/login', request.url)
    // pathname만 넘기면 쿼리스트링이 사라져, 검색 결과에서 물건을 클릭해 로그인한 뒤
    // 돌아왔을 때 목록 내 이전/다음 물건 컨텍스트(?ids=...&i=...)를 잃는다.
    // 원래 이동하려던 URL 전체를 보존해야 한다(docs/FRONTEND_MASTER_SPEC.md §3.4).
    // 값 자체는 로그인 화면에서 sanitizeRedirectPath()가 다시 검증한다(Open Redirect 방어 유지).
    loginUrl.searchParams.set('redirect', request.nextUrl.pathname + request.nextUrl.search)
    return NextResponse.redirect(loginUrl)
  }

  return supabaseResponse
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}
