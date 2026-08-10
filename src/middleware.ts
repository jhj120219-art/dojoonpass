// ================================================================
// Next.js 미들웨어
// 목적: 모든 요청마다 세션 자동 갱신 + 비로그인 유저 접근 차단
// ================================================================

import { createServerClient } from '@supabase/ssr'
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export async function middleware(request: NextRequest) {
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
  const PROTECTED_PREFIXES = ['/properties', '/favorites']
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