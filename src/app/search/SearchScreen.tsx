import SearchForm from './SearchForm'
import SearchPresets from './SearchPresets'
import SortBar from './SortBar'
import ResultList from './ResultList'
import Pagination from './Pagination'
import { fetchJSON } from '@/lib/api'
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

  // 로그인 상태면 검색 결과에 is_favorited가 채워지도록 토큰을 넘긴다.
  // fetchJSON은 이미 token을 optional로 받으므로 비로그인(undefined)도 기존과 동일하게 동작한다.
  const supabase = await createServerSupabaseClient()
  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token

  let data: SearchResponse | null = null
  let error: string | null = null
  try {
    data = await fetchJSON<SearchResponse>(`/api/v1/search${qs ? `?${qs}` : ''}`, token)
  } catch {
    error = '검색 결과를 불러오지 못했습니다'
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
        {error && <p className="text-center text-sm text-red-400 py-10">{error}</p>}
        {data && (
          <>
            <ResultList data={data} basePath={basePath} />
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
