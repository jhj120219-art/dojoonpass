'use client'
import { useState } from 'react'
import { putJSON, ApiError } from '@/lib/api'
import { createClient } from '@/lib/supabaseClient'

/**
 * 관심물건 메모/태그 — 보기 + 편집 (2026-08-28 Sprint 270).
 *
 * ## 왜 이 컴포넌트가 필요한가
 *
 * 가져오기(`/favorites/import`)가 메모를 **쓰기만** 하고 끝나면, 그 뒤로 고칠 방법이
 * 없다. 백엔드에는 `PUT /api/v1/favorites/{id}/note` 가 있는데 부르는 화면이 없으면
 * **도달 불가 기능**이다 — 이 저장소가 `crawl_date` 정렬에서 이미 겪은 모양이다
 * (타입/화이트리스트에는 있는데 UI 가 노출하지 않아 URL 을 직접 편집해야 썼다).
 *
 * ## 카드의 `<Link>` **밖**에 있어야 한다
 *
 * 관심물건 카드 전체가 상세로 가는 링크다. 입력칸을 그 안에 두면 글자를 고치려고
 * 누르는 순간 화면이 이동한다. 그래서 카드 컨테이너는 `<div>` 로 두고 링크는 위쪽
 * 정보 영역에만 걸며, 이 컴포넌트는 그 **형제**로 놓는다.
 *
 * ## 저장 결과를 반드시 말한다
 *
 * 저장은 화면 변화가 거의 없는 동작이라 성공했는지 알 수 없다. `role="status"` 로
 * 알린다(스크린리더도 읽는다). 실패도 정직하게 말한다 — 조용히 성공한 척하면
 * 사용자는 메모가 남았다고 믿는다. 메모 기능이 아직 준비되지 않은 환경
 * (migration 026 미적용)에서는 서버가 `FAVORITE_NOTE_UNAVAILABLE` 을 주므로
 * 그 사유를 그대로 전한다.
 */
export default function FavoriteNote({
  itemId,
  memo,
  tags,
}: {
  itemId: number
  memo: string
  tags: string[]
}) {
  const [editing, setEditing] = useState(false)
  const [draftMemo, setDraftMemo] = useState(memo)
  const [draftTags, setDraftTags] = useState(tags.join(', '))
  // 저장된 값. 서버가 정규화한 결과를 그대로 되받아 화면에 반영한다 —
  // 우리가 따로 정규화하면 서버와 화면이 갈린다(태그 중복 제거/길이 상한은 서버 규칙이다).
  const [saved, setSaved] = useState({ memo, tags })
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    setMessage('')
    try {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      const token = session?.access_token ?? null
      if (!token) {
        setMessage('로그인이 필요합니다')
        return
      }
      const res = await putJSON<{ memo: string; tags: string }>(
        `/api/v1/favorites/${itemId}/note`,
        {
          memo: draftMemo,
          // 쉼표/공백 어느 쪽으로 적어도 받는다. 최종 정규화는 서버가 한다.
          tags: draftTags.split(/[,\s]+/).filter(Boolean),
          source: null,
        },
        token
      )
      if (!res.success || !res.data) {
        setMessage(res.message ?? '저장하지 못했습니다')
        return
      }
      setSaved({
        memo: res.data.memo,
        tags: res.data.tags ? res.data.tags.split(',').filter(Boolean) : [],
      })
      setEditing(false)
      setMessage('저장했습니다')
    } catch (err) {
      // 408(타임아웃) 포함 모든 실패를 같은 문구로 알린다 — 사용자가 할 일은 하나다(다시 시도).
      setMessage(err instanceof ApiError && err.detail ? err.detail : '저장하지 못했습니다')
    } finally {
      setBusy(false)
    }
  }

  if (!editing) {
    const empty = !saved.memo && saved.tags.length === 0
    return (
      <div className="mt-2 border-t border-gray-50 pt-2">
        {saved.memo && (
          <p className="text-sm text-gray-600 line-clamp-2">{saved.memo}</p>
        )}
        {saved.tags.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {saved.tags.map((tag) => (
              <span
                key={tag}
                className="text-xs text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded-lg"
              >
                #{tag}
              </span>
            ))}
          </div>
        )}
        <div className="mt-1 flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setDraftMemo(saved.memo)
              setDraftTags(saved.tags.join(', '))
              setMessage('')
              setEditing(true)
            }}
            className="text-sm text-blue-500 font-medium"
          >
            {/* 비어 있을 때도 버튼을 감추지 않는다 — 사라지는 UI 는 "기능이 없다"로 읽힌다 */}
            {empty ? '메모 추가' : '메모 수정'}
          </button>
          {message && (
            <span role="status" className="text-sm text-gray-500">{message}</span>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="mt-2 border-t border-gray-50 pt-2 space-y-1">
      <textarea
        aria-label="메모"
        value={draftMemo}
        onChange={(e) => setDraftMemo(e.target.value)}
        rows={2}
        maxLength={1000}
        placeholder="메모"
        className="w-full rounded-xl border border-gray-200 px-3 py-1.5 text-sm text-gray-700 placeholder:text-gray-500"
      />
      <input
        aria-label="태그 (쉼표로 구분)"
        value={draftTags}
        onChange={(e) => setDraftTags(e.target.value)}
        maxLength={200}
        placeholder="태그 (쉼표로 구분)"
        className="w-full rounded-xl border border-gray-200 px-3 py-1.5 text-sm text-gray-700 placeholder:text-gray-500"
      />
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="rounded-xl bg-blue-500 px-3 py-1.5 text-sm font-medium text-white disabled:bg-gray-200 disabled:text-gray-500"
        >
          {busy ? '저장 중...' : '저장'}
        </button>
        <button
          type="button"
          onClick={() => {
            setEditing(false)
            setMessage('')
          }}
          className="text-sm text-gray-500"
        >
          취소
        </button>
        {message && (
          <span role="alert" className="text-sm text-red-500">{message}</span>
        )}
      </div>
    </div>
  )
}
