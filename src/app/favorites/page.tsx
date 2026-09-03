'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { fetchAuthedJSON, ApiError } from '@/lib/api'
import { createClient } from '@/lib/supabaseClient'
import { formatPrice } from '@/lib/format'
import SiteHeader from '@/components/SiteHeader'
import ResultThumbnail from '@/components/ResultThumbnail'
import ExportButtons from './ExportButtons'
import FavoriteNote from './FavoriteNote'
import { CONTAINER } from '@/lib/layout'

interface FavoriteItem {
  id: number
  case_no: string
  item_no: string | null
  court_name: string | null
  property_type: string | null
  sido: string | null
  sigungu: string | null
  full_address: string | null
  // 2026-09-03 — 검색/상세 타입과 같은 정정. 이 엔드포인트의 직렬화도
  // (`api/v1/favorites.py` / `api/v1/recent_items.py`) DB 행을 보정 없이 그대로 내보내고,
  // `auction_item` 의 이 컬럼들은 NOT NULL 이 아니다.
  appraisal_price: number | null
  minimum_bid_price: number | null
  bid_rate: number | null
  auction_date: string | null
  status: string | null
  fail_count: number | null
  /** 대표 사진(가장 앞선 순번)의 서빙 URL. 사진이 없는 물건은 null 이다. */
  thumbnail_url: string | null
  favorited_at: string
  /** 사용자 메모/태그 (2026-08-28, migration 026). 없으면 빈 값이지 null 이 아니다 —
      화면이 `?? ''` 분기를 만들 필요가 없게 백엔드가 그렇게 맞춰 준다. */
  memo: string
  tags: string[]
  /** 메모의 출처. **응답에는 있었는데 이 타입에만 없었다**(2026-08-31 소스 대조로 추가).
      `favorite_notes.source` — 마이리스트 가져오기가 "어디서 옮겨 왔는지"를 적어 둔다
      (`api/v1/favorite_import.py`). 없으면 빈 문자열이지 null 이 아니다(memo/tags 와 같은 규칙).
      화면에 보여 줄지는 정보 구성 결정이라 여기서 정하지 않고 계약만 적는다 —
      선언되지 않은 키는 "응답에 없는 것"으로 읽혀 이미 있는 데이터를 다시 만들게 한다. */
  note_source: string
}

export default function FavoritesPage() {
  const router = useRouter()
  const [items, setItems] = useState<FavoriteItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetchData() {
      const supabase = await createClient()
      const { data: { session } } = await supabase.auth.getSession()
      const token = session?.access_token ?? null
      if (!token) {
        router.push('/login?redirect=/favorites')
        return
      }
      try {
        const result = await fetchAuthedJSON<FavoriteItem[]>('/api/v1/favorites', token)
        setItems(result.data ?? [])
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          router.push('/login?redirect=/favorites')
          return
        }
        setError('관심물건을 불러오지 못했습니다')
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [router])

  if (loading) {
    return (
      <main className="min-h-screen bg-white flex items-center justify-center">
        <p className="text-gray-400">불러오는 중...</p>
      </main>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader current="favorites" title="관심물건" />
      <main className={`${CONTAINER} py-4`}>
        {error && <p role="alert" className="text-sm text-red-500 text-center py-20">{error}</p>}
        {!error && items && items.length === 0 && (
          <div className="text-center py-20">
            <p className="text-gray-400">관심물건이 없습니다.</p>
            {/* 빈 상태가 막다른 길이 되지 않게 다음 행동을 준다 —
                다른 곳에서 이미 목록을 갖고 있는 사용자가 가장 먼저 만나는 화면이다. */}
            <Link
              href="/favorites/import"
              className="mt-3 inline-block rounded-xl bg-gray-100 px-4 py-2.5 text-sm font-medium text-gray-600"
            >
              다른 목록에서 가져오기
            </Link>
          </div>
        )}
        {/* 내보내기 (2026-08-20 Sprint 227).
            0건이어도 버튼을 감추지 않는다 — 사라지는 UI 는 "기능이 없다"로 읽힌다.
            대신 비활성으로 두어 담은 것이 없다는 사실만 전한다. */}
        {!error && items && (
          <div className="flex flex-wrap items-center justify-end gap-2 pb-3">
            {/* 가져오기(2026-08-28)는 내보내기 **옆**에 둔다 — 같은 성격의 동작이고,
                0건일 때 가장 필요한 기능이라 빈 목록에서도 비활성화하지 않는다. */}
            <Link
              href="/favorites/import"
              className="rounded-xl bg-gray-100 px-4 py-2 text-sm font-medium text-gray-600"
            >
              목록 가져오기
            </Link>
            <ExportButtons rows={items} disabled={items.length === 0} />
          </div>
        )}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 items-start">
        {!error && items && items.map((item) => (
          // ★ `min-w-0` — grid 항목의 min-width 기본값 auto 때문에 트랙이 카드
          //   min-content(= truncate 문단의 문자열 전체 폭)까지 벌어졌다.
          //   실측(2026-08-21, 실제 320px 창): 컨테이너 257px vs 카드 728px,
          //   오른쪽 끝 744px -> 페이지 전체 가로 스크롤. 자세한 사유는
          //   src/app/search/ResultList.tsx 의 같은 자리 주석 참고.
          // ★ 카드 전체를 <Link> 로 감싸지 않는다 (2026-08-28 Sprint 270).
          //   메모 편집 입력칸이 링크 안에 있으면 글자를 고치려고 누르는 순간
          //   상세로 이동한다. 링크는 **정보 영역에만** 걸고 메모는 그 형제로 둔다.
          //   상세로 가는 동선은 그대로다 — 누르는 면적만 카드 아래쪽에서 빠진다.
          <div key={item.id} className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100 min-w-0">
            <Link href={`/properties/${item.id}`} className="block min-w-0">
              {/* 대표 사진 (2026-08-20 Sprint 224).

                  사용자는 검색목록에서 **사진을 보고** 담는다. 그런데 여기서는 사진이
                  사라져 같은 물건인지 알아보기 어려웠다. 검색목록과 같은 컴포넌트
                  (`@/components/ResultThumbnail`)와 같은 URL 규칙을 쓴다.

                  `thumbnail_url` 이 있을 때만 그린다 — 사진이 없는 물건에 빈 회색 칸을
                  만들면 오히려 카드가 나빠진다(이 저장소의 사진 보유율은 아직 낮다).
                  깨진 URL 은 컴포넌트가 onError 로 스스로 자리를 지운다. */}
              <div className="min-w-0 flex gap-3">
                {item.thumbnail_url && <ResultThumbnail url={item.thumbnail_url} />}
                <div className="min-w-0 flex-1">
                  {/* ★ `flex-wrap` — 좁은 화면에서 물건종류 배지가 세로로 한 글자씩 쪼개지는 것을 막는다.
                      실측 근거와 수치는 src/app/search/ResultList.tsx 의 같은 자리 주석 참고
                      (2026-08-21 Sprint 242, 실제 320px 뷰포트에서 9줄 -> 카드 403px). */}
                  <div className="flex flex-wrap items-start justify-between mb-1">
                    <span className="text-xs font-medium text-blue-500 bg-blue-50 px-2 py-1 rounded-lg">
                      {item.property_type || '-'}
                    </span>
                    <span className="text-xs text-gray-400">{item.auction_date || '-'} 매각</span>
                  </div>
                  <p className="text-sm font-bold text-gray-900 truncate">
                    {item.case_no}{item.item_no ? ` (${item.item_no})` : ''}
                  </p>
                  <p className="text-xs text-gray-400 truncate">
                    {item.full_address || [item.sido, item.sigungu].filter(Boolean).join(' ') || '-'}
                  </p>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-center border-t border-gray-50 pt-3">
                <div>
                  <p className="text-[0.6875rem] text-gray-400">감정가</p>
                  <p className="text-sm font-medium text-gray-700">{formatPrice(item.appraisal_price)}</p>
                </div>
                <div>
                  <p className="text-[0.6875rem] text-gray-400">최저입찰가</p>
                  <p className="text-sm font-bold text-blue-500">{formatPrice(item.minimum_bid_price)}</p>
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-gray-400">
                <span>{item.court_name || '-'}</span>
                <span>{new Date(item.favorited_at).toLocaleDateString('ko-KR')} 찜함</span>
              </div>
            </Link>
            {/* 메모/태그 보기 + 편집. 가져오기가 쓴 값을 나중에 고칠 수 있어야
                `PUT /api/v1/favorites/{id}/note` 가 도달 가능한 기능이 된다. */}
            <FavoriteNote itemId={item.id} memo={item.memo} tags={item.tags} />
          </div>
        ))}
        </div>
      </main>
    </div>
  )
}
