'use client'

// ================================================================
// 임장(현장 확인) 화면 — DISCOVER → REVIEW → **FIELD** → DECIDE
//
// ## 이 화면은 현장에서 쓴다
//
// 그래서 PC 입력폼을 그대로 줄여 놓지 않았다. 전제가 다르다:
//
//   한 손        엄지 하나로 닿는 곳에 체크와 판단 버튼을 둔다
//   장갑/추위    터치 영역을 크게 잡는다(min-h-14 = 56px, 애플/구글 권장 44~48px 이상)
//   서서 쓴다    화면 이동을 만들지 않는다 — 체크·메모·판단이 **한 화면**에 있다
//   회선 불안    누를 때마다 **즉시 저장**한다. "저장" 버튼을 따로 두면 전파가 끊긴
//                곳에서 사용자가 적은 것이 통째로 사라진다
//   손이 바쁘다  입력을 최소화한다. 체크는 탭 한 번, 메모는 선택 사항이다
//
// ## 판단을 대신하지 않는다
//
// 하단의 BID/HOLD/DROP 은 **사용자가 고르는 것**이다. 점수·추천·수익률을 계산해
// 보여 주지 않는다 — `docs/decision-log.md` 가 프로젝트 범위 밖으로 못박았다.
// ================================================================
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { createClient } from '@/lib/supabaseClient'
import { ApiError, fetchAuthedJSON, postJSON, putJSON } from '@/lib/api'

interface FieldCheck {
  key: string
  label: string
  checked: boolean
  note: string | null
  /** REVIEW 에서 **이미 확인된 사실**. 현장에서 대조할 대상이지 판단이 아니다.
      모르면 null — 서버가 "정보 없음" 같은 문구를 지어내지 않는다. */
  known: string | null
}

/** 이 화면이 **어느 물건인지**. 값이 없으면 null — 서버가 문구를 지어내지 않는다. */
interface FieldItemIdentity {
  case_no: string | null
  item_no: string | null
  court_name: string | null
  full_address: string | null
}

interface FieldVisit {
  item_id: number
  /** 현장에서 "지금 어느 물건에 적고 있는가"를 화면을 떠나지 않고 확인하게 한다. */
  item: FieldItemIdentity
  status: string
  started_at: string
  completed_at: string | null
  memo: string | null
  risk_note: string | null
  decision: string | null
  decided_at: string | null
  checks: FieldCheck[]
  checked_count: number
  check_total: number
  /** 몇 항목이 REVIEW 데이터로 미리 채워졌는가. 화면이 세지 않는다. */
  known_count: number
}

// 판단 값의 정본은 서버(`api/v1/field_visits.py:DECISIONS`)다. 화면은 **문구만** 갖는다 —
// 값을 새로 정의하지 않는다(서버가 모르는 값을 보내면 400 이 온다).
const DECISION_LABEL: Record<string, string> = {
  BID: '입찰',
  HOLD: '보류',
  DROP: '포기',
}
const DECISION_ORDER = ['BID', 'HOLD', 'DROP'] as const

export default function FieldVisitPage() {
  const params = useParams()
  const router = useRouter()
  const rawId = Array.isArray(params?.id) ? params.id[0] : params?.id
  const itemId = Number(rawId)

  const [visit, setVisit] = useState<FieldVisit | null>(null)
  const [loading, setLoading] = useState(true)
  // 'none'      아직 시작하지 않았다 (404) — "임장 시작" 을 그린다
  // 'unavailable' migration 030 미적용 (503) — 사용자 잘못이 아니라고 말한다
  // 'error'     그 밖의 실패
  const [state, setState] = useState<'ok' | 'none' | 'unavailable' | 'error'>('ok')
  const [saving, setSaving] = useState(false)
  const [memo, setMemo] = useState('')
  const [risk, setRisk] = useState('')

  const loginRedirect = `/login?redirect=/properties/${rawId}/field`

  const token = useCallback(async () => {
    const supabase = await createClient()
    const { data: { session } } = await supabase.auth.getSession()
    return session?.access_token ?? null
  }, [])

  // 서버 응답 한 벌을 화면 상태로 옮기는 자리도 **하나만** 둔다 —
  // 저장 경로가 넷(체크/메모/완료/판단)이라 각자 옮기면 한쪽만 갱신되는 날이 온다.
  const apply = useCallback((next: FieldVisit) => {
    setVisit(next)
    setMemo(next.memo ?? '')
    setRisk(next.risk_note ?? '')
    setState('ok')
  }, [])

  const handleError = useCallback((err: unknown) => {
    if (err instanceof ApiError) {
      if (err.status === 401 || err.status === 403) {
        router.push(loginRedirect)
        return
      }
      if (err.status === 404) { setState('none'); return }
      if (err.status === 503) { setState('unavailable'); return }
    }
    setState('error')
  }, [router, loginRedirect])

  useEffect(() => {
    let alive = true
    async function load() {
      if (!Number.isFinite(itemId)) { setState('error'); setLoading(false); return }
      const t = await token()
      if (!t) { router.push(loginRedirect); return }
      try {
        const res = await fetchAuthedJSON<FieldVisit>(`/api/v1/field-visits/${itemId}`, t)
        if (!alive) return
        if (res.data) apply(res.data)
      } catch (err) {
        if (alive) handleError(err)
      } finally {
        if (alive) setLoading(false)
      }
    }
    load()
    return () => { alive = false }
  }, [itemId, token, router, loginRedirect, apply, handleError])

  async function start() {
    const t = await token()
    if (!t) { router.push(loginRedirect); return }
    setSaving(true)
    try {
      const res = await postJSON<FieldVisit>('/api/v1/field-visits', { item_id: itemId }, t)
      if (res.data) apply(res.data)
    } catch (err) { handleError(err) } finally { setSaving(false) }
  }

  async function toggleCheck(item: FieldCheck) {
    const t = await token()
    if (!t) { router.push(loginRedirect); return }
    // 낙관적 반영 — 현장에서 탭이 즉시 반응해야 한다. 실패하면 서버 응답으로 되돌아온다.
    setVisit((prev) => prev && {
      ...prev,
      checks: prev.checks.map((c) => c.key === item.key ? { ...c, checked: !c.checked } : c),
      checked_count: prev.checked_count + (item.checked ? -1 : 1),
    })
    try {
      const res = await putJSON<FieldVisit>(
        `/api/v1/field-visits/${itemId}/checks`,
        { check_key: item.key, checked: !item.checked }, t)
      if (res.data) apply(res.data)
    } catch (err) { handleError(err) }
  }

  // 메모는 타이핑마다 보내지 않는다 — 포커스를 벗어날 때 한 번 저장한다.
  // (현장 회선에서 글자마다 요청을 보내면 느려지고 배터리를 먹는다.)
  const savedMemo = useRef<{ memo: string; risk: string }>({ memo: '', risk: '' })
  useEffect(() => {
    savedMemo.current = { memo: visit?.memo ?? '', risk: visit?.risk_note ?? '' }
  }, [visit])

  async function saveNotes() {
    if (memo === savedMemo.current.memo && risk === savedMemo.current.risk) return
    const t = await token()
    if (!t) { router.push(loginRedirect); return }
    setSaving(true)
    try {
      const res = await putJSON<FieldVisit>(
        `/api/v1/field-visits/${itemId}/notes`, { memo, risk_note: risk }, t)
      if (res.data) apply(res.data)
    } catch (err) { handleError(err) } finally { setSaving(false) }
  }

  async function complete() {
    const t = await token()
    if (!t) { router.push(loginRedirect); return }
    setSaving(true)
    try {
      const res = await postJSON<FieldVisit>(
        `/api/v1/field-visits/${itemId}/complete`, {}, t)
      if (res.data) apply(res.data)
    } catch (err) { handleError(err) } finally { setSaving(false) }
  }

  async function decide(decision: string) {
    const t = await token()
    if (!t) { router.push(loginRedirect); return }
    setSaving(true)
    try {
      const res = await putJSON<FieldVisit>(
        `/api/v1/field-visits/${itemId}/decision`, { decision }, t)
      if (res.data) apply(res.data)
    } catch (err) { handleError(err) } finally { setSaving(false) }
  }

  const backHref = `/properties/${rawId}`

  if (loading) {
    return <main className="mx-auto max-w-[560px] px-4 py-10 text-gray-600">불러오는 중...</main>
  }

  if (state === 'unavailable') {
    return (
      <main className="mx-auto max-w-[560px] px-4 py-10">
        <h1 className="text-lg font-bold text-gray-900">임장 기록</h1>
        {/* 사용자 잘못이 아니라는 것을 분명히 말한다 — "서버 오류"로 뭉뚱그리면
            사용자는 자기가 뭘 잘못했는지 찾는다. */}
        <p className="mt-4 text-sm text-gray-600">
          임장 기능이 아직 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.
        </p>
        <Link href={backHref} className="mt-6 inline-block text-sm text-blue-600 underline">
          물건 상세로 돌아가기
        </Link>
      </main>
    )
  }

  if (state === 'error') {
    return (
      <main className="mx-auto max-w-[560px] px-4 py-10">
        <h1 className="text-lg font-bold text-gray-900">임장 기록</h1>
        <p className="mt-4 text-sm text-gray-600">임장 기록을 불러오지 못했습니다.</p>
        <Link href={backHref} className="mt-6 inline-block text-sm text-blue-600 underline">
          물건 상세로 돌아가기
        </Link>
      </main>
    )
  }

  if (state === 'none' || !visit) {
    return (
      <main className="mx-auto max-w-[560px] px-4 py-10">
        <Link href={backHref} className="text-sm text-blue-600 underline">← 물건 상세</Link>
        <h1 className="mt-4 text-lg font-bold text-gray-900">임장 기록</h1>
        <p className="mt-2 text-sm text-gray-600">
          현장에서 확인할 항목을 미리 받아 두고, 본 것을 바로 기록합니다.
        </p>
        <button
          type="button"
          onClick={start}
          disabled={saving}
          className="mt-6 min-h-14 w-full rounded-xl bg-blue-600 px-4 text-base font-bold
                     text-white disabled:opacity-60"
        >
          {saving ? '시작하는 중...' : '임장 시작'}
        </button>
      </main>
    )
  }

  const done = visit.status === 'DONE'

  return (
    // max-w-[560px]: 현장은 한 손 세로 화면이다. 검색/상세가 쓰는 1320px 컨테이너를
    // 쓰지 않는 이유가 이것이다 — 그 폭은 표를 보는 화면의 것이다.
    <main className="mx-auto max-w-[560px] px-4 pb-28 pt-4">
      <Link href={backHref} className="text-sm text-blue-600 underline">← 물건 상세</Link>

      <header className="mt-3">
        <div className="flex items-baseline justify-between">
          <h1 className="text-lg font-bold text-gray-900">임장 기록</h1>
          <span className="text-sm text-gray-600" aria-live="polite">
            {visit.checked_count}/{visit.check_total} 확인
            {done ? ' · 완료' : ''}
          </span>
        </div>
        {/* 어느 물건인지 — 현장에서는 하루에 여러 건을 돈다. 이 줄이 없으면 엉뚱한
            물건에 적어도 화면이 아무 말을 하지 않고, 확인하려면 상세로 나갔다
            돌아와야 한다. 값이 없는 자리는 그리지 않는다(빈 문구를 만들지 않는다). */}
        {(visit.item.full_address || visit.item.case_no) && (
          <p className="mt-1 text-sm text-gray-700">
            {visit.item.full_address && (
              <span className="font-medium">{visit.item.full_address}</span>
            )}
            {visit.item.full_address && visit.item.case_no && ' · '}
            {visit.item.case_no && (
              <span>
                {visit.item.case_no}
                {visit.item.item_no && visit.item.item_no !== '1'
                  ? ` (${visit.item.item_no})`
                  : ''}
              </span>
            )}
          </p>
        )}
      </header>

      {/* 현장에 가기 전에 "무엇을 확인해야 하는지"를 이미 알고 있게 한다.
          아래 항목마다 붙은 "자료:" 가 상세 화면에서 본 것이고, 현장에서는 그것이
          실제와 맞는지만 대조하면 된다. */}
      {visit.known_count > 0 && (
        <p className="mt-2 text-sm text-gray-600">
          {visit.check_total}개 중 {visit.known_count}개는 자료로 미리 확인됐습니다.
          현장에서는 자료와 실제가 같은지 대조하세요.
        </p>
      )}

      {/* 체크리스트 — 탭 한 번으로 즉시 저장 */}
      <ul className="mt-4 space-y-2">
        {visit.checks.map((c) => (
          <li key={c.key}>
            <button
              type="button"
              onClick={() => toggleCheck(c)}
              aria-pressed={c.checked}
              className={`flex min-h-14 w-full items-start gap-3 rounded-xl border px-4 py-3
                          text-left text-base ${
                c.checked
                  ? 'border-blue-600 bg-blue-50 text-blue-900'
                  : 'border-gray-300 bg-white text-gray-800'
              }`}
            >
              <span
                aria-hidden="true"
                className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full
                            border-2 text-sm font-bold ${
                  c.checked ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-400 text-transparent'
                }`}
              >
                ✓
              </span>
              <span className="min-w-0">
                <span className="block">{c.label}</span>
                {/* REVIEW 에서 이미 아는 것. 현장에서 **대조할 대상**이라 항목 바로
                    아래에 붙인다 — 별도 패널로 빼면 다시 화면을 오가게 된다. */}
                {c.known && (
                  <span className="mt-1 block text-sm font-normal text-gray-600">
                    자료: {c.known}
                  </span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>

      {/* 메모 / 위험요소 — 선택 사항이다. 짧게 적는 것을 전제로 rows 를 작게 둔다. */}
      <div className="mt-6 space-y-4">
        <div>
          <label htmlFor="field-memo" className="block text-sm font-bold text-gray-900">
            현장 메모
          </label>
          <textarea
            id="field-memo"
            // placeholder 는 입력을 시작하면 사라지므로 **이름이 아니다**.
            // 보이는 라벨과 같은 문구로 이름을 명시한다(WCAG 2.5.3).
            aria-label="현장 메모"
            value={memo}
            onChange={(e) => setMemo(e.target.value)}
            onBlur={saveNotes}
            rows={3}
            placeholder="본 것을 짧게"
            className="mt-2 w-full rounded-xl border border-gray-300 p-3 text-base"
          />
        </div>
        <div>
          <label htmlFor="field-risk" className="block text-sm font-bold text-gray-900">
            위험요소
          </label>
          <textarea
            id="field-risk"
            aria-label="위험요소"
            value={risk}
            onChange={(e) => setRisk(e.target.value)}
            onBlur={saveNotes}
            rows={2}
            placeholder="걸리는 점"
            className="mt-2 w-full rounded-xl border border-gray-300 p-3 text-base"
          />
        </div>
      </div>

      {/* 판단 — DECIDE 로 넘어가는 자리. 값은 사용자가 고른다. */}
      <section className="mt-8">
        <h2 className="text-sm font-bold text-gray-900">입찰 판단</h2>
        {/* 3등분 버튼. `grid-cols-3` 를 쓰지 않는 이유 —
            저장소 규칙이 반응형 접두사 없는 3열 이상 그리드를 막는다(좁은 화면에서
            카드가 100px 대로 눌리기 때문). 여기는 두 글자 버튼 셋이라 그 문제가
            없지만, 규칙의 예외를 만들기보다 같은 배치를 flex 로 표현한다. */}
        <div className="mt-2 flex gap-2">
          {DECISION_ORDER.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => decide(d)}
              aria-pressed={visit.decision === d}
              disabled={saving}
              className={`min-h-14 flex-1 rounded-xl border text-base font-bold disabled:opacity-60 ${
                visit.decision === d
                  ? 'border-gray-900 bg-gray-900 text-white'
                  : 'border-gray-300 bg-white text-gray-800'
              }`}
            >
              {DECISION_LABEL[d]}
            </button>
          ))}
        </div>
      </section>

      {/* 완료 — 화면 아래 고정. 엄지가 닿는 자리다. */}
      <div className="fixed inset-x-0 bottom-0 border-t border-gray-200 bg-white p-4">
        <div className="mx-auto max-w-[560px]">
          <button
            type="button"
            onClick={complete}
            disabled={saving}
            className="min-h-14 w-full rounded-xl bg-gray-900 px-4 text-base font-bold
                       text-white disabled:opacity-60"
          >
            {done ? '임장 완료됨 · 다시 저장' : '임장 완료'}
          </button>
        </div>
      </div>
    </main>
  )
}
