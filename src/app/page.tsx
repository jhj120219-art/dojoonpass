import SearchScreen from './search/SearchScreen'

type HomePageProps = {
  searchParams: Promise<Record<string, string>>
}

// docs/FRONTEND_MASTER_SPEC.md §4 — 첫 진입 화면은 로그인 화면이 아니라 **검색 화면 자체**다.
// 예전에는 이 파일이 UI 없이 세션만 확인하고 무조건 redirect했다
// (로그인 → /properties, 비로그인 → /login). 그 구조가 "첫 화면 로그인 강제"의 직접 원인이라
// redirect를 전부 제거하고 검색 화면을 그대로 렌더한다. 로그인 여부로 분기하지 않는다.
export default async function HomePage({ searchParams }: HomePageProps) {
  const params = await searchParams
  return <SearchScreen searchParams={params} basePath="/" />
}
