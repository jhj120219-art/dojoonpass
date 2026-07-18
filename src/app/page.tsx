import { redirect } from 'next/navigation'
import { createServerSupabaseClient } from '@/lib/supabaseServer'

export default async function HomePage() {
  // 서버에서 현재 로그인 세션 확인
  const supabase = await createServerSupabaseClient()
  const { data: { user } } = await supabase.auth.getUser()

  // 로그인된 유저 → 매물 리스트로 이동
  if (user) {
    redirect('/properties')
  }

  // 비로그인 유저 → 로그인 페이지로 이동
  redirect('/login')
}