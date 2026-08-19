'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname, useSearchParams } from 'next/navigation'
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
  // SearchForm과 동일한 이유로 '/search' 하드코딩을 걷어낸다 — 저장된 조건을 적용하거나
  // 로그인으로 유도할 때 지금 보고 있는 화면(`/` 또는 `/search`)을 벗어나지 않아야 한다.
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [presets, setPresets] = useState<SearchPreset[]>([])
  const [listLoading, setListLoading] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  // 로그인 복귀 시 입력하던 이름을 되살린다(위 redirectToLogin 참고).
  // 최초 렌더에서만 URL을 읽는다 — 이후 사용자의 타이핑을 URL이 덮어쓰면 안 되기 때문이다.
  const [name, setName] = useState(() => searchParams.get('preset_name') ?? '')
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
      } catch (err) {
        // 401/403은 "불러오기 실패"가 아니라 **세션이 더 이상 유효하지 않다**는 뜻이다.
        // (브라우저에 남은 만료 토큰으로 getSession()이 세션을 돌려주는 경우가 실제로 있다.)
        // 그때 빨간 에러를 띄우면, 비로그인 사용자에게 고칠 수도 없는 실패를 보여주는 꼴이 된다.
        // 저장/삭제 경로가 이미 401/403을 로그인 유도로 처리하는 것과 같은 규칙을 목록 조회에도 적용해
        // 비로그인 상태(=아래 "로그인하면 검색조건을 저장할 수 있습니다" 안내)로 되돌린다.
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          setAccessToken(null)
        } else {
          setListError('저장된 검색조건을 불러오지 못했습니다')
        }
      } finally {
        setListLoading(false)
      }
    }
    init()
  }, [])

  // 로그인 후 돌아왔을 때 입력하던 검색조건 이름을 되살리기 위한 쿼리 키.
  // FILTER_PARAM_KEYS에 없는 값이라 검색 조건으로도, 저장되는 conditions로도 새어 들어가지
  // 않는다(currentConditions/SearchForm 둘 다 FILTER_PARAM_KEYS만 읽는다).
  const PRESET_NAME_PARAM = 'preset_name'

  function redirectToLogin(pendingName?: string) {
    // 검색조건(쿼리스트링)은 이미 보존되고 있었지만, **입력하던 이름은 사라졌다** —
    // 이름을 쓰고 저장을 누른 비로그인 사용자가 로그인 후 돌아오면 빈 칸을 다시 채워야 했다
    // (2026-08-11 Sprint 52). 복귀 URL에 이름을 실어 그대로 되살린다.
    const params = new URLSearchParams(searchParams.toString())
    if (pendingName) params.set(PRESET_NAME_PARAM, pendingName)
    else params.delete(PRESET_NAME_PARAM)
    const qs = params.toString()
    const target = qs ? `${pathname}?${qs}` : pathname
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
      // 입력하던 이름을 들고 로그인으로 간다 — 복귀 후 그대로 이어서 저장할 수 있도록.
      redirectToLogin(trimmedName)
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
    router.push(qs ? `${pathname}?${qs}` : pathname)
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
          aria-label="검색조건 이름"
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
      {saveError && <p role="alert" className="text-xs text-red-500 mt-2">{saveError}</p>}

      {!authChecked ? null : !accessToken ? (
        <p className="text-xs text-gray-400 mt-3">로그인하면 검색조건을 저장하고 불러올 수 있습니다</p>
      ) : (
        <div className="mt-3 pt-3 border-t border-gray-50">
          {listLoading && <p className="text-xs text-gray-400">불러오는 중...</p>}
          {listError && <p role="alert" className="text-xs text-red-500">{listError}</p>}
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
