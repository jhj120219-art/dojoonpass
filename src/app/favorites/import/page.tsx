'use client'
import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { fetchAuthedJSON, postJSON, ApiError } from '@/lib/api'
import { createClient } from '@/lib/supabaseClient'
import { formatPrice } from '@/lib/format'
import SiteHeader from '@/components/SiteHeader'
import { CONTAINER } from '@/lib/layout'

// ================================================================
// 마이리스트 가져오기 — 2026-08-28 신설
//
// ## 무엇을 만들었나
//
// 사용자가 **다른 곳에서 관리하던 관심물건 목록을 손으로 복사해** 여기 붙여넣으면,
// 우리 물건과 맞춰 보고 확인한 뒤 관심물건으로 담는 화면이다.
// `/favorites` 의 내보내기(Sprint 227)와 정확히 반대 방향이고, 우리 CSV/TSV 를
// 그대로 되붙이는 것도 같은 입력으로 받는다.
//
// ## 무엇을 만들지 않았나 (중요)
//
// **외부 상용 서비스에 로그인하거나 자동으로 긁어 오는 기능은 만들지 않는다.**
// 이 화면이 다루는 입력은 사용자가 자기 클립보드에 담아 온 텍스트 하나뿐이다.
// 서비스명 목록(지지옥션/탱크옥션 …)도 두지 않는다 — 목록을 두는 순간 그 자체가
// "우리가 그 서비스와 연동한다"는 잘못된 신호가 된다. 출처는 자유 입력으로 받는다.
//
// ## 화면 구조는 새로 만들지 않는다
//
// SiteHeader + CONTAINER + 카드 + Loading/Empty/Error 는 `/favorites` 가 쓰던 것을
// 그대로 쓴다(docs/FRONTEND_MASTER_SPEC.md §11.2 "동일 기능의 중복 컴포넌트를 만들지
// 않는다"). 새 공통 컴포넌트도 만들지 않았다.
//
// ## 판단을 사용자에게 남기는 자리
//
//   AMBIGUOUS  후보가 여럿이다 — **우리가 고르지 않는다.** 사용자가 고른 것만 담는다.
//   NOT_FOUND  못 찾은 줄을 지우지 않는다. 원문을 그대로 보여 준다.
//              (조용히 사라지면 사용자는 "다 가져와졌다"고 믿는다)
// ================================================================

const LOGIN_REDIRECT = '/login?redirect=/favorites/import'

type Candidate = {
  id: number
  case_no: string
  item_no: string | null
  court_name: string | null
  property_type: string | null
  full_address: string | null
  appraisal_price: number | null
  minimum_bid_price: number | null
  auction_date: string | null
  status: string | null
}

type PreviewRow = {
  line_no: number
  raw: string
  case_no: string
  item_no: string | null
  court_name: string | null
  address: string | null
  memo: string
  tags: string[]
  source: string
  status: string
  item_id: number | null
  candidates: Candidate[]
  narrowed_by: string[]
}

type PreviewData = {
  rows: PreviewRow[]
  summary: Record<string, number>
  truncated: boolean
  header_detected: boolean
  notes_enabled: boolean
  source: string
}

type CommitResult = {
  item_id: number
  status: string
  reason: string | null
  note_written?: boolean
}

type CommitData = {
  results: CommitResult[]
  summary: { added: number; already: number; failed: number; total: number }
  notes_enabled: boolean
}

// 백엔드 상태값(normalizer/mylist_import.py)에 한국어 라벨만 붙인다.
// 모르는 값이 오면 **원본을 그대로 노출한다** — 뭉뚱그리면 새로 생긴 상태를 오해한다
// (`/mypage` 가 쓰는 규칙과 동일).
const STATUS_LABEL: Record<string, string> = {
  MATCHED: '가져올 수 있음',
  ALREADY_FAVORITED: '이미 관심물건',
  AMBIGUOUS: '물건 선택 필요',
  NOT_FOUND: '찾지 못함',
  NO_CASE_NO: '사건번호 없음',
  DUPLICATE_IN_INPUT: '입력 안에서 중복',
}
const STATUS_TONE: Record<string, string> = {
  MATCHED: 'bg-blue-50 text-blue-600',
  ALREADY_FAVORITED: 'bg-gray-100 text-gray-500',
  AMBIGUOUS: 'bg-orange-50 text-orange-600',
  NOT_FOUND: 'bg-red-50 text-red-500',
  NO_CASE_NO: 'bg-red-50 text-red-500',
  DUPLICATE_IN_INPUT: 'bg-gray-100 text-gray-500',
}

const CARD = 'bg-white rounded-2xl p-5 shadow-sm border border-gray-100'
const SECTION_TITLE = 'text-sm font-bold text-gray-900 mb-3'

const PLACEHOLDER = [
  '다른 곳에서 정리해 둔 목록을 그대로 붙여넣으세요. 예:',
  '',
  '2024타경1009 서울중앙지방법원 물건번호 3 #관심',
  '2023타경30078-1  경기 안산시 단원구',
  '',
  '관심물건 내보내기로 받은 CSV/엑셀 표를 그대로 붙여넣어도 됩니다.',
].join('\n')

async function getToken(): Promise<string | null> {
  const supabase = await createClient()
  const { data: { session } } = await supabase.auth.getSession()
  return session?.access_token ?? null
}

export default function ImportPage() {
  const router = useRouter()
  const [text, setText] = useState('')
  const [source, setSource] = useState('')
  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [result, setResult] = useState<CommitData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // 사용자가 화면에서 내린 결정만 담는다. 서버가 준 `preview` 는 손대지 않는다 —
  // 두 상태를 한 곳에 섞으면 "서버가 말한 것"과 "사용자가 바꾼 것"을 구분할 수 없다.
  const [chosen, setChosen] = useState<Record<number, number>>({})   // line_no -> item_id
  const [excluded, setExcluded] = useState<Record<number, boolean>>({})
  const [memos, setMemos] = useState<Record<number, string>>({})

  function resolvedItemId(row: PreviewRow): number | null {
    if (row.status === 'AMBIGUOUS') return chosen[row.line_no] ?? null
    if (row.status === 'MATCHED' || row.status === 'ALREADY_FAVORITED') return row.item_id
    return null
  }

  // 담을 수 있는 줄 = 물건이 정해졌고 사용자가 제외하지 않은 것.
  // `ALREADY_FAVORITED` 도 포함한다 — 메모/태그를 새로 붙일 수 있고, 서버가 멱등이다.
  const selectable = (preview?.rows ?? []).filter(
    (r) => resolvedItemId(r) !== null && !excluded[r.line_no]
  )

  async function runPreview() {
    setError(null)
    setResult(null)
    setPreview(null)
    setChosen({})
    setExcluded({})
    setMemos({})
    if (!text.trim()) {
      setError('가져올 내용을 붙여넣어 주세요')
      return
    }
    setBusy(true)
    try {
      const token = await getToken()
      if (!token) {
        router.push(LOGIN_REDIRECT)
        return
      }
      const res = await postJSON<PreviewData>(
        '/api/v1/favorites/import/preview',
        { text, source: source.trim() || null },
        token
      )
      if (!res.success || !res.data) {
        setError(res.message ?? '가져올 내용을 확인하지 못했습니다')
        return
      }
      setPreview(res.data)
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        router.push(LOGIN_REDIRECT)
        return
      }
      setError('가져올 내용을 확인하지 못했습니다')
    } finally {
      setBusy(false)
    }
  }

  async function runCommit() {
    if (selectable.length === 0) return
    setError(null)
    setBusy(true)
    try {
      const token = await getToken()
      if (!token) {
        router.push(LOGIN_REDIRECT)
        return
      }
      const rows = selectable.map((r) => ({
        item_id: resolvedItemId(r),
        memo: memos[r.line_no] ?? r.memo,
        tags: r.tags,
        source: source.trim() || r.source || null,
      }))
      const res = await postJSON<CommitData>(
        '/api/v1/favorites/import/commit', { rows }, token
      )
      if (!res.success || !res.data) {
        setError(res.message ?? '가져오지 못했습니다')
        return
      }
      setResult(res.data)
      // 목록을 다시 불러 화면과 서버가 어긋나지 않게 한다. 실패해도 결과 요약은
      // 이미 보여 줬으므로 이 재조회 실패로 화면을 붉게 만들지 않는다.
      fetchAuthedJSON('/api/v1/favorites', token).catch(() => {})
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        router.push(LOGIN_REDIRECT)
        return
      }
      setError('가져오지 못했습니다')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader current="favorites" title="관심물건 가져오기" />
      <main className={`${CONTAINER} py-4 space-y-3`}>
        {/* --- 입력 --- */}
        <section className={CARD}>
          <h2 className={SECTION_TITLE}>목록 붙여넣기</h2>
          <p className="text-sm text-gray-500 mb-3">
            다른 곳에서 정리해 둔 관심물건 목록을 그대로 붙여넣으면 사건번호를 읽어
            콕찰 물건과 맞춰 봅니다. 확인한 뒤에만 저장됩니다.
          </p>
          <textarea
            id="import-text"
            aria-label="가져올 목록"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            placeholder={PLACEHOLDER}
            className="w-full rounded-xl border border-gray-200 p-3 text-sm text-gray-700 placeholder:text-gray-500"
          />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <label htmlFor="import-source" className="text-sm text-gray-500">
              출처 (선택)
            </label>
            <input
              id="import-source"
              aria-label="출처 (선택)"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              maxLength={50}
              placeholder="예: 내 엑셀 목록"
              className="rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-700 placeholder:text-gray-500"
            />
            <button
              type="button"
              onClick={runPreview}
              disabled={busy}
              className="ml-auto rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-medium text-white disabled:bg-gray-200 disabled:text-gray-500"
            >
              {busy ? '확인 중...' : '미리보기'}
            </button>
          </div>
          {error && <p role="alert" className="mt-3 text-sm text-red-500">{error}</p>}
        </section>

        {/* --- 결과 요약 (커밋 후) --- */}
        {result && (
          <section className={CARD} role="status">
            <h2 className={SECTION_TITLE}>가져오기 결과</h2>
            <ul className="text-sm text-gray-700 space-y-1">
              <li>새로 담은 물건 <b className="text-blue-500">{result.summary.added}</b>건</li>
              <li>이미 담겨 있던 물건 {result.summary.already}건</li>
              {/* 0건이어도 감추지 않는다 — 사라지는 줄은 "실패가 없었다"로 읽힌다 */}
              <li className={result.summary.failed > 0 ? 'text-red-500' : ''}>
                담지 못한 물건 {result.summary.failed}건
              </li>
              {!result.notes_enabled && (
                <li className="text-orange-500">
                  메모·태그는 저장되지 않았습니다 (기능 준비 중)
                </li>
              )}
            </ul>
            <Link
              href="/favorites"
              className="mt-3 inline-block rounded-xl bg-gray-100 px-4 py-2.5 text-sm font-medium text-gray-600"
            >
              관심물건으로 이동
            </Link>
          </section>
        )}

        {/* --- 미리보기 --- */}
        {preview && (
          <section className={CARD}>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <h2 className={`${SECTION_TITLE} mb-0`}>
                확인 ({preview.rows.length}줄)
              </h2>
              <button
                type="button"
                onClick={runCommit}
                disabled={busy || selectable.length === 0}
                className="rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-medium text-white disabled:bg-gray-200 disabled:text-gray-500"
              >
                {selectable.length}건 가져오기
              </button>
            </div>

            {/* 상태별 개수. 0인 상태도 서버가 키를 준다 — 감추지 않는다 */}
            <div className="flex flex-wrap gap-2 mb-3">
              {Object.keys(STATUS_LABEL).map((key) => (
                <span
                  key={key}
                  className={`text-xs px-2 py-1 rounded-lg ${STATUS_TONE[key] ?? 'bg-gray-100 text-gray-500'}`}
                >
                  {STATUS_LABEL[key]} {preview.summary[key] ?? 0}
                </span>
              ))}
            </div>

            {preview.truncated && (
              <p role="alert" className="text-sm text-orange-500 mb-3">
                입력이 너무 길어 앞의 {preview.rows.length}줄만 읽었습니다. 나머지는 나눠서 가져와 주세요.
              </p>
            )}
            {!preview.notes_enabled && (
              <p className="text-sm text-orange-500 mb-3">
                메모·태그 저장은 아직 준비 중입니다. 물건 담기는 정상 동작합니다.
              </p>
            )}

            {preview.rows.length === 0 && (
              <p className="text-sm text-gray-500 py-10 text-center">
                읽을 수 있는 줄을 찾지 못했습니다.
              </p>
            )}

            <ul className="space-y-3">
              {preview.rows.map((row) => {
                const chosenId = resolvedItemId(row)
                const off = !!excluded[row.line_no]
                return (
                  <li
                    key={row.line_no}
                    className="border-t border-gray-50 pt-3 first:border-0 first:pt-0 min-w-0"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-bold text-gray-900 truncate">
                          {row.case_no || '(사건번호 없음)'}
                          {row.item_no ? ` (${row.item_no})` : ''}
                        </p>
                        {/* 원문을 항상 보여 준다 — 못 찾은 줄에서 특히 중요하다 */}
                        <p className="text-sm text-gray-500 truncate">{row.raw}</p>
                      </div>
                      <span
                        className={`text-xs font-bold px-2 py-1 rounded-lg shrink-0 ${
                          STATUS_TONE[row.status] ?? 'bg-gray-100 text-gray-500'
                        }`}
                      >
                        {STATUS_LABEL[row.status] ?? row.status}
                      </span>
                    </div>

                    {/* 후보가 여럿이면 사용자가 고른다. 우리가 고르지 않는다. */}
                    {row.status === 'AMBIGUOUS' && (
                      <fieldset className="mt-2">
                        <legend className="text-sm text-gray-500 mb-1">
                          어느 물건인지 골라 주세요
                        </legend>
                        <div className="space-y-1">
                          {row.candidates.map((c) => (
                            <label
                              key={c.id}
                              className="flex items-start gap-2 text-sm text-gray-600"
                            >
                              <input
                                type="radio"
                                name={`cand-${row.line_no}`}
                                checked={chosen[row.line_no] === c.id}
                                onChange={() =>
                                  setChosen((p) => ({ ...p, [row.line_no]: c.id }))
                                }
                                className="mt-0.5 shrink-0"
                              />
                              <span className="min-w-0">
                                <span className="font-medium text-gray-700">
                                  {c.case_no}{c.item_no ? ` (${c.item_no})` : ''}
                                </span>
                                {' · '}{c.court_name || '-'}
                                {' · '}{c.full_address || '-'}
                                {' · 최저 '}
                                {c.minimum_bid_price == null
                                  ? '-'
                                  : formatPrice(c.minimum_bid_price)}
                              </span>
                            </label>
                          ))}
                        </div>
                      </fieldset>
                    )}

                    {/* 찾지 못한 줄은 무엇이 문제인지 알려 준다 */}
                    {row.status === 'NOT_FOUND' && (
                      <p className="mt-1 text-sm text-gray-500">
                        콕찰에 아직 없는 사건이거나 매각이 끝난 물건일 수 있습니다.
                      </p>
                    )}
                    {row.status === 'NO_CASE_NO' && (
                      <p className="mt-1 text-sm text-gray-500">
                        이 줄에서 사건번호(예: 2024타경1009)를 찾지 못했습니다.
                      </p>
                    )}

                    {chosenId !== null && (
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <label className="flex items-center gap-1.5 text-sm text-gray-500">
                          <input
                            type="checkbox"
                            checked={!off}
                            onChange={() =>
                              setExcluded((p) => ({ ...p, [row.line_no]: !off }))
                            }
                          />
                          가져오기
                        </label>
                        <input
                          id={`memo-${row.line_no}`}
                          aria-label={`${row.case_no || row.raw} 메모`}
                          value={memos[row.line_no] ?? row.memo}
                          onChange={(e) =>
                            setMemos((p) => ({ ...p, [row.line_no]: e.target.value }))
                          }
                          maxLength={1000}
                          placeholder="메모 (선택)"
                          className="flex-1 min-w-0 rounded-xl border border-gray-200 px-3 py-1.5 text-sm text-gray-700 placeholder:text-gray-500"
                        />
                        {row.tags.length > 0 && (
                          <span className="text-sm text-gray-500 shrink-0">
                            {row.tags.map((t) => `#${t}`).join(' ')}
                          </span>
                        )}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </section>
        )}
      </main>
    </div>
  )
}
