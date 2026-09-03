'use client'
import { useState, type MouseEvent } from 'react'
import { useRouter, usePathname, useSearchParams } from 'next/navigation'
import { postJSON, deleteJSON, ApiError, ERROR_CODES } from '@/lib/api'
import { createClient } from '@/lib/supabaseClient'

// Detail 페이지(properties/[id]/page.tsx)의 handleToggleFavorite와 동일한 토큰 확보 →
// POST/DELETE /api/v1/favorites → 401/403 처리 흐름을 그대로 재사용한다. 차이는 리다이렉트
// 대상뿐: Detail은 고정 경로(/properties/{id})지만, 여기서는 검색 조건(쿼리스트링)을 잃지
// 않도록 현재 검색 URL 전체를 redirect 대상으로 쓴다(src/proxy.ts와 동일하게
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

    const supabase = await createClient()
    const { data: { session } } = await supabase.auth.getSession()
    const token = session?.access_token ?? null
    if (!token) {
      setFavBusy(false)
      redirectToLogin()
      return
    }

    setFavError(null)
    try {
      // 서버가 실패를 반환했는데도 하트를 뒤집으면, 아이콘은 바뀌고 그 아래에 실패 메시지가
      // 함께 뜨는 모순된 화면이 된다. 상태는 "서버 기준으로 그렇게 됐을 때만" 바꾼다.
      //
      // 단 이미 원하는 상태인 경우(중복 등록 / 이미 삭제됨)는 실패가 아니라 **의도가 이미
      // 이뤄진 것**이므로, 상태만 맞추고 에러는 띄우지 않는다. 이 구분이 가능한 이유가
      // 도메인 Error Code다 — 메시지 문구로 분기하면 문구가 바뀌는 순간 깨진다.
      if (favorited) {
        const result = await deleteJSON<{ item_id: number }>(`/api/v1/favorites/${itemId}`, token)
        if (result.success || result.error === ERROR_CODES.FAVORITE_NOT_FOUND) {
          setFavorited(false)
        } else {
          setFavError(result.message ?? '즐겨찾기 삭제에 실패했습니다')
        }
      } else {
        const result = await postJSON<{ item_id: number; created_at: string }>('/api/v1/favorites', { item_id: itemId }, token)
        if (result.success || result.error === ERROR_CODES.FAVORITE_ALREADY_EXISTS) {
          setFavorited(true)
        } else {
          setFavError(result.message ?? '즐겨찾기 등록에 실패했습니다')
        }
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
        <span role="alert" className="absolute top-full right-0 mt-1 whitespace-nowrap text-[0.625rem] text-red-500 bg-white px-1.5 py-0.5 rounded shadow-sm border border-red-100 z-20">
          {favError}
        </span>
      )}
    </span>
  )
}
