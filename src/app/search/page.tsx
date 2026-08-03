import SearchForm from './SearchForm'
import SearchPresets from './SearchPresets'
import SortBar from './SortBar'
import ResultList from './ResultList'
import Pagination from './Pagination'
import { fetchJSON } from '@/lib/api'
import type { SearchResponse } from './types'
import PrimaryNav from '@/components/PrimaryNav'

type SearchPageProps = {
  searchParams: Promise<Record<string, string>>
}

export default async function SearchPage({ searchParams }: SearchPageProps) {
  const params = await searchParams
  const qs = new URLSearchParams(params).toString()

  let data: SearchResponse | null = null
  let error: string | null = null
  try {
    data = await fetchJSON<SearchResponse>(`/api/v1/search${qs ? `?${qs}` : ''}`)
  } catch {
    error = '검색 결과를 불러오지 못했습니다'
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-white border-b border-gray-100">
        <div className="max-w-[1320px] mx-auto px-8 py-4 flex items-center justify-between">
          <h1 className="text-lg font-bold text-gray-900">경매 물건 검색</h1>
          <PrimaryNav current="search" />
        </div>
      </div>
      <div className="max-w-[1320px] mx-auto px-8 py-4">
        <SearchForm />
        <SearchPresets />
        <SortBar />
        {error && <p className="text-center text-sm text-red-400 py-10">{error}</p>}
        {data && (
          <>
            <ResultList data={data} />
            <Pagination currentPage={data.page} totalPages={data.total_pages} />
          </>
        )}
      </div>
    </div>
  )
}
