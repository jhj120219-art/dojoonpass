'use client'

import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabaseClient'

export default function LogoutButton() {
  const router = useRouter()

  async function handleLogout() {
    const supabase = await createClient()
    await supabase.auth.signOut()
    // 로그아웃 후에는 로그인 화면이 아니라 첫 화면(=검색 화면)으로 보낸다
    // (docs/FRONTEND_MASTER_SPEC.md §5.3) — 로그아웃했다고 검색을 못 하게 만들지 않는다.
    router.push('/')
    // 서버 컴포넌트(SearchScreen)가 이전 세션 토큰으로 렌더한 결과(is_favorited 등)를
    // 그대로 두지 않도록 서버 렌더를 다시 태운다.
    router.refresh()
  }

  return (
    <button
      onClick={handleLogout}
      className="text-xs text-gray-400 hover:text-blue-500 transition-colors duration-200"
    >
      로그아웃
    </button>
  )
}
