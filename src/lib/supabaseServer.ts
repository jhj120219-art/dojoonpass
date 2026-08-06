// ================================================================
// 서버 컴포넌트 전용 Supabase 클라이언트
// 사용 위치: page.tsx 등 서버 컴포넌트에서 로그인 세션 확인할 때
// ================================================================

import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

export async function createServerSupabaseClient() {
  const cookieStore = await cookies()

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll()
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) => {
              cookieStore.set(name, value, options)
            })
          } catch {
            // 서버 컴포넌트에서 쿠키 쓰기 제한 시 무시 (middleware가 처리)
          }
        },
      },
    }
  )
}