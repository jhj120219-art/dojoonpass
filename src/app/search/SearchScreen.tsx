import SearchForm from './SearchForm'
import SearchPresets from './SearchPresets'
import SortBar from './SortBar'
import ResultList from './ResultList'
import Pagination from './Pagination'
import Link from 'next/link'
import { fetchJSON, ApiError } from '@/lib/api'
import type { SearchResponse } from './types'
import SiteHeader from '@/components/SiteHeader'
import { CONTAINER } from '@/lib/layout'
import { createServerSupabaseClient } from '@/lib/supabaseServer'

type SearchScreenProps = {
  searchParams: Record<string, string>
  // 이 화면이 렌더된 경로. `/`와 `/search`가 같은 컴포넌트를 쓰므로, 화면 안에서 만들어지는
  // 링크가 사용자를 다른 경로로 옮기지 않도록 호출한 라우트가 자기 경로를 알려준다.
  basePath: string
}

// docs/FRONTEND_MASTER_SPEC.md §4 — 첫 화면(`/`)과 기존 `/search`가 **공유하는 단일 검색 화면**.
// 두 라우트가 화면을 각자 복제하지 않도록(§11.2) 실제 구성은 전부 여기에 둔다.
//
// 검색 실행은 이 화면이 렌더된 경로(pathname)를 그대로 유지한 채 쿼리스트링만 갱신한다
// (SearchForm/SearchPresets가 usePathname 기준으로 push) — `/`에서 검색하면 `/`에 머문다.
export default async function SearchScreen({ searchParams, basePath }: SearchScreenProps) {
  const qs = new URLSearchParams(searchParams).toString()

  // 검색조건은 그대로 두고 page만 뗀 URL. 페이지 번호가 범위를 벗어났을 때(예: 북마크한
  // `?page=3`이 결과 건수 감소로 오늘은 범위 밖) 조건을 잃지 않고 1페이지로 돌아가는 동선이다.
  const firstPageParams = new URLSearchParams(searchParams)
  firstPageParams.delete('page')
  const firstPageQs = firstPageParams.toString()
  const firstPageHref = firstPageQs ? `${basePath}?${firstPageQs}` : basePath

  // 결과 0건의 원인은 두 갈래이고 안내도 복구 동선도 달라야 한다.
  //   (a) 사용자의 검색조건이 너무 좁다      -> 조건을 풀면 결과가 나온다
  //   (b) 카탈로그 자체에 살아있는 물건이 없다 -> 조건을 풀어도 0건이다
  // 예전에는 둘을 구분하지 않고 항상 "검색조건을 줄여보세요 / 조건 없이 전체 물건 보기"를
  // 띄웠다. (b)에서는 그 안내가 틀렸을 뿐 아니라 복구 링크가 **같은 빈 화면으로 되돌아오는
  // 막다른 길**이 된다. 기본 필터가 `auction_date >= 오늘`이라 크롤이 멈추면 (b)는 가정이
  // 아니라 예정된 상태다(2026-08-17 실측: 미래 물건 9건, 전부 2026-08-19 -> 08-20부터 0건).
  //
  // 조건이 걸려 있는지는 검색 파라미터로 판별한다. page/size/sort_by/sort_order는 조건이
  // 아니라 표시 방식이므로 제외한다(정렬만 바꿔도 (a)로 오판하면 안 된다).
  const NON_FILTER_PARAMS = new Set(['page', 'size', 'sort_by', 'sort_order'])
  const hasFilters = Object.entries(searchParams).some(
    ([k, v]) => !NON_FILTER_PARAMS.has(k) && v !== undefined && v !== '',
  )

  // 로그인 상태면 검색 결과에 is_favorited가 채워지도록 토큰을 넘긴다.
  // fetchJSON은 이미 token을 optional로 받으므로 비로그인(undefined)도 기존과 동일하게 동작한다.
  const supabase = await createServerSupabaseClient()
  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token

  let data: SearchResponse | null = null
  // 실패 원인을 두 갈래로 나눈다. 예전에는 어떤 실패든 "검색 결과를 불러오지 못했습니다"
  // 한 줄만 띄웠는데, `?size=500`·`?size=abc`·`?page=0`처럼 **URL 파라미터가 잘못된 경우**에도
  // 서버가 죽은 것처럼 보이는 문구가 나오고 되돌아갈 동선이 전혀 없었다(북마크·공유 URL에서
  // 실제로 도달한다). 백엔드는 이런 값을 400/422로 명확히 거부하므로 그 정보를 살린다.
  let errorKind: 'bad_request' | 'unavailable' | null = null
  // 서버가 준 정확한 사유(있을 때만). 2026-08-17 Sprint 162 —
  // 아래 고정 안내문은 페이지/개수만 언급하는데, 400은 sort_by·min_appraisal 등
  // 다른 조건에서도 난다. 그때 고정 문구만 보여 주면 **엉뚱한 곳을 고치라는 안내**가 된다.
  let errorDetail: string | undefined
  try {
    data = await fetchJSON<SearchResponse>(`/api/v1/search${qs ? `?${qs}` : ''}`, token)
  } catch (err) {
    errorKind =
      err instanceof ApiError && (err.status === 400 || err.status === 422)
        ? 'bad_request'
        : 'unavailable'
    if (err instanceof ApiError) errorDetail = err.detail
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader current="search" title="경매 물건 검색" />
      {/* 본문 랜드마크. 스크린리더가 헤더를 건너뛰고 검색/결과로 바로 갈 수 있어야 한다
          (Sprint 47 접근성 감사: main 랜드마크가 0개였다). */}
      <main className={`${CONTAINER} py-4`}>
        <SearchForm />
        <SearchPresets />
        <SortBar />
        {/* 결과 영역이 실패해도 위의 검색 Form은 그대로 쓸 수 있어야 한다(Master Spec §13 #4) */}
        {errorKind === 'bad_request' && (
          <div className="text-center py-20">
            <p className="text-gray-500 font-medium">검색조건에 잘못된 값이 있습니다</p>
            {/* 서버가 어느 조건이 왜 틀렸는지 알려 주면 그것을 그대로 보여 준다
                (예: "허용되지 않는 sort_by 값입니다: BOGUS").
                FastAPI 검증 오류처럼 사유가 문자열이 아니면 아래 기본 안내로 떨어진다. */}
            {errorDetail ? (
              <p className="mt-1 text-sm text-gray-400">{errorDetail}</p>
            ) : (
              <p className="mt-1 text-sm text-gray-400">
                주소창의 검색조건 중 일부가 허용되지 않는 값입니다
                (페이지 번호는 1 이상, 한 페이지 개수는 1~100).
              </p>
            )}
            <Link
              href={basePath}
              className="mt-4 inline-block rounded-xl bg-blue-500 px-4 py-2 text-sm font-medium text-white"
            >
              검색조건 초기화
            </Link>
          </div>
        )}
        {errorKind === 'unavailable' && (
          <p className="text-center text-sm text-red-400 py-10">검색 결과를 불러오지 못했습니다</p>
        )}
        {data && (
          <>
            <ResultList
              data={data}
              basePath={basePath}
              firstPageHref={firstPageHref}
              hasFilters={hasFilters}
            />
            {/* 결과가 0건이면 페이지 크기(20/30/50/100)와 이전/다음은 조작할 대상이 없다.
                빈 화면에 비활성 컨트롤만 남아 Empty State의 안내를 가리던 것을 없앤다. */}
            {data.total > 0 && (
              <Pagination currentPage={data.page} totalPages={data.total_pages} />
            )}
          </>
        )}
      </main>
    </div>
  )
}
