import SearchScreen from './SearchScreen'

type SearchPageProps = {
  searchParams: Promise<Record<string, string>>
}

// `/`와 동일한 검색 화면. 기존 링크/북마크/`?redirect=` 호환을 위해 라우트를 유지한다
// (docs/FRONTEND_MASTER_SPEC.md §2.1). 화면 구성은 SearchScreen 하나만 쓰고 복제하지 않는다.
export default async function SearchPage({ searchParams }: SearchPageProps) {
  const params = await searchParams
  return <SearchScreen searchParams={params} basePath="/search" />
}
