'use client'

import { useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { fetchAuthedJSON, postJSON, deleteJSON, ApiError } from '@/lib/api'
import { createClient } from '@/lib/supabaseClient'
import { FILTER_PARAM_KEYS } from './SearchForm'

interface SearchPreset {
  id: number
  name: string
  conditions: Record<string, string>
  created_at: string
}

// FILTER_PARAM_KEYS(=검색조건 키)만 URL에서 뽑아 저장 대상 conditions를 만든다.
// sort_by/sort_order/size/page는 SearchForm.tsx의 기존 분류대로 "검색조건이 아님"이라 제외한다.
function currentConditions(searchParams: URLSearchParams | ReturnType<typeof useSearchParams>): Record<string, string> {
  const result: Record<string, string> = {}
  for (const key of FILTER_PARAM_KEYS) {
    const value = searchParams.get(key)
    if (value) result[key] = value
  }
  return result
}

export default function SearchPresets() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [presets, setPresets] = useState<SearchPreset[]>([])
  const [listLoading, setListLoading] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  useEffect(() => {
    async function init() {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      const token = session?.access_token ?? null
      setAccessToken(token)
      setAuthChecked(true)
      if (!token) return
      setListLoading(true)
      try {
        const result = await fetchAuthedJSON<SearchPreset[]>('/api/v1/search-presets', token)
        setPresets(result.data ?? [])
      } catch {
        setListError('저장된 검색조건을 불러오지 못했습니다')
      } finally {
        setListLoading(false)
      }
    }
    init()
  }, [])

  function redirectToLogin() {
    const qs = searchParams.toString()
    const target = qs ? `/search?${qs}` : '/search'
    const loginParams = new URLSearchParams()
    loginParams.set('redirect', target)
    router.push(`/login?${loginParams.toString()}`)
  }

  async function handleSave() {
    if (saving) return
    const trimmedName = name.trim()
    if (!trimmedName) {
      setSaveError('이름을 입력해주세요')
      return
    }
    if (!accessToken) {
      redirectToLogin()
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      const conditions = currentConditions(searchParams)
      const result = await postJSON<{ id: number; name: string; created_at: string }>(
        '/api/v1/search-presets',
        { name: trimmedName, conditions },
        accessToken
      )
      if (result.success && result.data) {
        const saved = result.data
        setPresets((prev) => [{ id: saved.id, name: saved.name, conditions, created_at: saved.created_at }, ...prev])
        setName('')
      } else {
        setSaveError(result.message ?? '저장에 실패했습니다')
      }
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        redirectToLogin()
      } else {
        setSaveError('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
      }
    } finally {
      setSaving(false)
    }
  }

  // 저장된 conditions(URL 파라미터와 동일한 문자열 값)를 그대로 새 쿼리스트링으로 만들어
  // 기존 "URL → SearchForm 초기값 → 검색 API" 흐름을 그대로 태운다. page는 항상 생략(=1페이지).
  function applyPreset(preset: SearchPreset) {
    const params = new URLSearchParams()
    for (const key of FILTER_PARAM_KEYS) {
      const value = preset.conditions[key]
      if (typeof value === 'string' && value) params.set(key, value)
    }
    const sortBy = searchParams.get('sort_by')
    const sortOrder = searchParams.get('sort_order')
    const size = searchParams.get('size')
    if (sortBy) params.set('sort_by', sortBy)
    if (sortOrder) params.set('sort_order', sortOrder)
    if (size) params.set('size', size)
    const qs = params.toString()
    router.push(qs ? `/search?${qs}` : '/search')
  }

  async function handleDelete(id: number) {
    if (deletingId !== null) return
    if (!accessToken) {
      redirectToLogin()
      return
    }
    setDeletingId(id)
    setListError(null)
    try {
      const result = await deleteJSON<{ id: number }>(`/api/v1/search-presets/${id}`, accessToken)
      if (result.success) {
        setPresets((prev) => prev.filter((p) => p.id !== id))
      } else {
        setListError(result.message ?? '삭제에 실패했습니다')
      }
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        redirectToLogin()
      } else {
        setListError('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
      }
    } finally {
      setDeletingId(null)
    }
  }

  const inputClass =
    'flex-1 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200'

  return (
    <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100 mb-4">
      <h2 className="text-sm font-bold text-gray-900 mb-2">검색조건 저장</h2>
      <div className="flex gap-2">
        <input
          type="text"
          placeholder="검색조건 이름"
          value={name}
          maxLength={50}
          onChange={(e) => setName(e.target.value)}
          className={inputClass}
        />
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="shrink-0 rounded-xl bg-blue-500 px-4 py-2 text-sm font-medium text-white active:bg-blue-600 transition-colors disabled:opacity-50"
        >
          저장
        </button>
      </div>
      {saveError && <p className="text-xs text-red-500 mt-2">{saveError}</p>}

      {!authChecked ? null : !accessToken ? (
        <p className="text-xs text-gray-400 mt-3">로그인하면 검색조건을 저장하고 불러올 수 있습니다</p>
      ) : (
        <div className="mt-3 pt-3 border-t border-gray-50">
          {listLoading && <p className="text-xs text-gray-400">불러오는 중...</p>}
          {listError && <p className="text-xs text-red-500">{listError}</p>}
          {!listLoading && !listError && presets.length === 0 && (
            <p className="text-xs text-gray-400">저장된 검색조건이 없습니다</p>
          )}
          {!listLoading && presets.length > 0 && (
            <ul className="space-y-1.5">
              {presets.map((preset) => (
                <li key={preset.id} className="flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => applyPreset(preset)}
                    className="flex-1 text-left text-sm text-blue-500 font-medium truncate"
                  >
                    {preset.name}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(preset.id)}
                    disabled={deletingId === preset.id}
                    className="shrink-0 text-xs text-gray-400 disabled:opacity-50"
                  >
                    삭제
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
