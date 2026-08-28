'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { fetchAuthedJSON, ApiError } from '@/lib/api'
import { createClient } from '@/lib/supabaseClient'
import { formatWon } from '@/lib/format'
import SiteHeader from '@/components/SiteHeader'
import { CONTAINER } from '@/lib/layout'

// ================================================================
// 마이페이지 — 2026-08-11 Sprint 54 신설
//
// **새 화면 스펙을 만들지 않았다.** 이 화면은 이미 있는 사용자 API 3개를 그대로 나열할 뿐이고,
// 화면 구조(SiteHeader + CONTAINER + 카드 + Loading/Empty/Error)는 `/favorites`와
// `/properties/recent`가 쓰던 패턴을 **글자 그대로** 따른다. 새 컴포넌트도 만들지 않는다
// (docs/FRONTEND_MASTER_SPEC.md §11.2 "동일 기능의 중복 컴포넌트를 만들지 않는다").
//
// 조합하는 기존 API (전부 "내 것만" 돌려주는 인증 필수 엔드포인트):
//   GET /api/v1/subscriptions/me   구독 현황 (Sprint 52 신설 — 이전에는 사용자가 볼 방법이 없었다)
//   GET /api/v1/payments           결제 내역
//   GET /api/v1/registry-requests  등기부 신청 내역
// 관심물건 / 최근 본 물건은 이미 전용 화면이 있으므로 **링크만** 둔다(중복 구현 금지).
//
// 임의로 정하지 않은 것:
//   - 어떤 정보를 강조할지, 카드 순서, 요약 지표 같은 **UX/제품 판단**은 하지 않았다.
//     API가 돌려주는 것을 그대로, 서버가 정한 순서(최신순)대로 보여준다.
//   - 구독 해지/변경 같은 **액션은 넣지 않았다** — 해지 정책이 미정이고(사업 결정),
//     사용자용 해지 엔드포인트도 없다. 조회 전용 화면이다.
// ================================================================

interface Subscription {
  id: number
  plan: string
  price: number
  status: string
  started_at: string
  expires_at: string | null
  effective_status: string
  is_entitled: boolean
  grace_period_end: string | null
}

interface Payment {
  id: number
  payment_type: string
  amount: number
  status: string
  created_at: string
}

interface RegistryRequest {
  id: number
  item_id: number
  case_no: string | null
  full_address: string | null
  status: string
  reason: string | null
  requested_at: string
}

const LOGIN_REDIRECT = '/login?redirect=/mypage'

// 상태 표기는 백엔드 값(api/constants.py)을 그대로 쓰되 한국어 라벨만 붙인다.
// 알 수 없는 값이 오면 **원본 값을 그대로 노출한다** — 임의로 뭉뚱그리면 운영 중
// 새로 생긴 상태를 사용자가 오해한다.
const SUBSCRIPTION_LABEL: Record<string, string> = {
  ACTIVE: '이용 중',
  GRACE_PERIOD: '유예 기간',
  PAUSED: '일시정지',
  EXPIRED: '만료됨',
  CANCELLED: '해지됨',
}
const PAYMENT_LABEL: Record<string, string> = {
  PAID: '결제 완료',
  SUCCESS: '결제 완료',
  FAILED: '결제 실패',
  CANCELLED: '취소됨',
  EXPIRED: '기한 만료',
  PARTIAL_REFUND: '부분 환불',
  REFUNDED: '환불 완료',
}
const PAYMENT_TYPE_LABEL: Record<string, string> = {
  SUBSCRIPTION: '구독',
  OVERAGE_USAGE: '등기부 초과 이용',
}
const REGISTRY_LABEL: Record<string, string> = {
  PENDING: '접수됨',
  PAYMENT_REQUIRED: '결제 필요',
  PROCESSING: '처리 중',
  COMPLETED: '발급 완료',
  FAILED: '신청 실패',
}

function formatDate(value: string | null): string {
  if (!value) return '-'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString('ko-KR')
}

const CARD = 'bg-white rounded-2xl p-5 shadow-sm border border-gray-100'
const SECTION_TITLE = 'text-sm font-bold text-gray-900 mb-3'

export default function MyPage() {
  const router = useRouter()
  const [subscriptions, setSubscriptions] = useState<Subscription[] | null>(null)
  const [payments, setPayments] = useState<Payment[] | null>(null)
  const [registryRequests, setRegistryRequests] = useState<RegistryRequest[] | null>(null)
  // 섹션별 오류를 따로 둔다 — 하나가 실패해도 나머지는 보여야 한다.
  // (`/favorites`는 단일 목록이라 오류도 하나지만, 여기는 세 API를 조합하므로 분리한다)
  const [errors, setErrors] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetchAll() {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      const token = session?.access_token ?? null
      if (!token) {
        router.push(LOGIN_REDIRECT)
        return
      }

      let expired = false
      const failed: Record<string, boolean> = {}

      // 세 API를 병렬로 부른다 — 순차로 부르면 화면이 느려지기만 하고 서로 의존하지 않는다.
      async function load<T>(key: string, path: string, set: (v: T[]) => void) {
        try {
          const result = await fetchAuthedJSON<T[]>(path, token!)
          set(result.data ?? [])
        } catch (err) {
          // 401/403은 "불러오기 실패"가 아니라 세션 만료다 — 로그인으로 보낸다
          // (SearchPresets가 이미 쓰는 규칙과 동일).
          if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
            expired = true
          } else {
            failed[key] = true
          }
        }
      }

      await Promise.all([
        load<Subscription>('subscriptions', '/api/v1/subscriptions/me', setSubscriptions),
        load<Payment>('payments', '/api/v1/payments', setPayments),
        load<RegistryRequest>('registry', '/api/v1/registry-requests', setRegistryRequests),
      ])

      if (expired) {
        router.push(LOGIN_REDIRECT)
        return
      }
      setErrors(failed)
      setLoading(false)
    }
    fetchAll()
  }, [router])

  if (loading) {
    return (
      <main className="min-h-screen bg-white flex items-center justify-center">
        <p className="text-gray-400">불러오는 중...</p>
      </main>
    )
  }

  const entitled = subscriptions?.find((s) => s.is_entitled) ?? null

  return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader current="mypage" title="마이페이지" />
      <main className={`${CONTAINER} py-4 space-y-3 xl:space-y-0 xl:grid xl:grid-cols-2 xl:gap-3 xl:items-start`}>
        {/* --- 구독 현황 --- */}
        <section className={CARD}>
          <h2 className={SECTION_TITLE}>구독</h2>
          {errors.subscriptions ? (
            <p role="alert" className="text-sm text-red-500">구독 정보를 불러오지 못했습니다</p>
          ) : !subscriptions || subscriptions.length === 0 ? (
            <p className="text-sm text-gray-400">구독 내역이 없습니다</p>
          ) : (
            <div className="space-y-3">
              {entitled ? (
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-400">현재 상태</span>
                  <span className="text-xs font-bold px-2 py-1 rounded-lg bg-green-50 text-green-600">
                    {SUBSCRIPTION_LABEL[entitled.effective_status] ?? entitled.effective_status}
                  </span>
                </div>
              ) : (
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-400">현재 상태</span>
                  <span className="text-xs font-bold px-2 py-1 rounded-lg bg-gray-100 text-gray-500">
                    이용 중인 구독 없음
                  </span>
                </div>
              )}
              {subscriptions.map((sub) => (
                <div key={sub.id} className="pb-3 border-b border-gray-50 last:border-0 last:pb-0 space-y-1">
                  <div className="flex justify-between">
                    <span className="text-sm font-medium text-gray-700">{sub.plan}</span>
                    <span className="text-sm text-gray-600">
                      {SUBSCRIPTION_LABEL[sub.effective_status] ?? sub.effective_status}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-gray-400">결제 금액</span>
                    <span className="text-xs text-gray-600">{formatWon(sub.price)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-gray-400">이용 기간</span>
                    <span className="text-xs text-gray-600">
                      {formatDate(sub.started_at)} ~ {formatDate(sub.expires_at)}
                    </span>
                  </div>
                  {/* 유예 기간은 만료 시각을 지난 뒤의 상태다 — 언제까지 쓸 수 있는지 알려준다 */}
                  {sub.effective_status === 'GRACE_PERIOD' && sub.grace_period_end && (
                    <div className="flex justify-between">
                      <span className="text-xs text-gray-400">유예 종료</span>
                      <span className="text-xs text-orange-500">{formatDate(sub.grace_period_end)}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* --- 결제 내역 --- */}
        <section className={CARD}>
          <h2 className={SECTION_TITLE}>결제 내역</h2>
          {errors.payments ? (
            <p role="alert" className="text-sm text-red-500">결제 내역을 불러오지 못했습니다</p>
          ) : !payments || payments.length === 0 ? (
            <p className="text-sm text-gray-400">결제 내역이 없습니다</p>
          ) : (
            <ul className="space-y-2">
              {payments.map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-700 truncate">
                      {PAYMENT_TYPE_LABEL[p.payment_type] ?? p.payment_type}
                    </p>
                    <p className="text-xs text-gray-400">{formatDate(p.created_at)}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-sm font-bold text-blue-500">{formatWon(p.amount)}</p>
                    <p className="text-xs text-gray-400">{PAYMENT_LABEL[p.status] ?? p.status}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* --- 등기부 신청 내역 --- */}
        <section className={CARD}>
          <h2 className={SECTION_TITLE}>등기부 신청</h2>
          {errors.registry ? (
            <p role="alert" className="text-sm text-red-500">등기부 신청 내역을 불러오지 못했습니다</p>
          ) : !registryRequests || registryRequests.length === 0 ? (
            <p className="text-sm text-gray-400">등기부 신청 내역이 없습니다</p>
          ) : (
            <ul className="space-y-2">
              {registryRequests.map((r) => (
                <li key={r.id}>
                  {/* 상세로 이동해 다운로드/재신청을 이어갈 수 있어야 한다 — 상세 화면이
                      이미 등기부 카드를 갖고 있으므로 그쪽으로 보낸다(기능 중복 구현 금지) */}
                  <Link href={`/properties/${r.item_id}`} className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-700 truncate">{r.case_no || '-'}</p>
                      <p className="text-xs text-gray-400 truncate">{r.full_address || '-'}</p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-xs text-gray-600">{REGISTRY_LABEL[r.status] ?? r.status}</p>
                      <p className="text-xs text-gray-400">{formatDate(r.requested_at)}</p>
                    </div>
                  </Link>
                  {r.status === 'FAILED' && r.reason && (
                    <p className="text-xs text-red-500 mt-0.5">{r.reason}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* --- 이미 전용 화면이 있는 것들은 링크만 --- */}
        <section className={CARD}>
          <h2 className={SECTION_TITLE}>내 물건</h2>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/favorites"
              className="flex-1 text-center rounded-xl bg-gray-100 px-4 py-2.5 text-sm font-medium text-gray-600"
            >
              관심물건
            </Link>
            <Link
              href="/properties/recent"
              className="flex-1 text-center rounded-xl bg-gray-100 px-4 py-2.5 text-sm font-medium text-gray-600"
            >
              최근 본 물건
            </Link>
            {/* 2026-08-28 — 다른 곳에서 관리하던 목록을 가져오는 진입점.
                마이페이지에 두는 이유: 처음 온 사용자가 "내 것을 옮겨 오는" 일을
                찾는 자리가 여기다. 화면 자체는 /favorites/import 하나뿐이고
                여기서는 링크만 둔다(기능 중복 구현 금지). */}
            <Link
              href="/favorites/import"
              className="flex-1 text-center rounded-xl bg-gray-100 px-4 py-2.5 text-sm font-medium text-gray-600"
            >
              목록 가져오기
            </Link>
          </div>
        </section>
      </main>
    </div>
  )
}
