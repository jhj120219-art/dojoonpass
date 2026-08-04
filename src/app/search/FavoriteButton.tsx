'use client'
import { useState, type MouseEvent } from 'react'
import { useRouter, usePathname, useSearchParams } from 'next/navigation'
import { postJSON, deleteJSON, ApiError } from '@/lib/api'
import { createClient } from '@/lib/supabaseClient'

// Detail 페이지(properties/[id]/page.tsx)의 handleToggleFavorite와 동일한 토큰 확보 →
// POST/DELETE /api/v1/favorites → 401/403 처리 흐름을 그대로 재사용한다. 차이는 리다이렉트
// 대상뿐: Detail은 고정 경로(/properties/{id})지만, 여기서는 검색 조건(쿼리스트링)을 잃지
// 않도록 현재 검색 URL 전체를 redirect 대상으로 쓴다(middleware.ts와 동일하게
// URLSearchParams로 인코딩).
export default function FavoriteButton({ itemId, initialFavorited }: { itemId: number; initialFavorited: boolean }) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const [favorited, setFavorited] = useState(initialFavorited)
  const [favBusy, setFavBusy] = useState(false)
  const [favError, setFavError] = useState<string | null>(null)

  function currentSearchUrl() {
    const qs = searchParams.toString()
    return qs ? `${pathname}?${qs}` : pathname
  }

  function redirectToLogin() {
    const loginParams = new URLSearchParams({ redirect: currentSearchUrl() })
    router.push(`/login?${loginParams.toString()}`)
  }

  async function handleToggleFavorite(e: MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    if (favBusy) return
    // getSession()이 끝나기 전에 재클릭이 들어오면 이 시점의 favBusy는 아직 false라
    // 위 가드를 그대로 통과한다 — await 이전에 동기적으로 busy 처리해 재진입을 막는다.
    setFavBusy(true)

    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    const token = session?.access_token ?? null
    if (!token) {
      setFavBusy(false)
      redirectToLogin()
      return
    }

    setFavError(null)
    try {
      if (favorited) {
        const result = await deleteJSON<{ item_id: number }>(`/api/v1/favorites/${itemId}`, token)
        setFavorited(false)
        if (!result.success) setFavError(result.message ?? '즐겨찾기 삭제에 실패했습니다')
      } else {
        const result = await postJSON<{ item_id: number; created_at: string }>('/api/v1/favorites', { item_id: itemId }, token)
        setFavorited(true)
        if (!result.success) setFavError(result.message ?? '즐겨찾기 등록에 실패했습니다')
      }
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setFavError('로그인이 만료되었습니다. 다시 로그인해주세요')
        redirectToLogin()
      } else {
        setFavError('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
      }
    } finally {
      setFavBusy(false)
    }
  }

  return (
    <span className="relative inline-block shrink-0">
      <button
        type="button"
        onClick={handleToggleFavorite}
        disabled={favBusy}
        aria-label={favorited ? '즐겨찾기 해제' : '즐겨찾기 추가'}
        title={favorited ? '즐겨찾기됨' : '즐겨찾기 안됨'}
        className="text-lg disabled:opacity-50"
      >
        {favorited ? '❤️' : '🤍'}
      </button>
      {favError && (
        <span className="absolute top-full right-0 mt-1 whitespace-nowrap text-[10px] text-red-500 bg-white px-1.5 py-0.5 rounded shadow-sm border border-red-100 z-20">
          {favError}
        </span>
      )}
    </span>
  )
}
