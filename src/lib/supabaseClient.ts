// ================================================================
// 브라우저(클라이언트 컴포넌트)용 Supabase 연결 파일
// 사용 위치: 'use client' 선언된 컴포넌트에서 import해서 사용
// ================================================================

import { createBrowserClient } from '@supabase/ssr'

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  )
}