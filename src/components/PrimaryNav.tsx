import Link from 'next/link'

export type PrimaryNavCurrent = 'search' | 'recent' | 'favorites' | 'mypage'

type PrimaryNavProps = {
  current?: PrimaryNavCurrent
}

const NAV_ITEMS: { key: PrimaryNavCurrent; href: string; label: string }[] = [
  // 검색 메뉴는 첫 화면(`/`)을 가리킨다 — `/`가 곧 검색 화면이기 때문
  // (docs/FRONTEND_MASTER_SPEC.md §7.2). `/search`도 계속 동작하지만 링크 대상은 `/`로 통일한다.
  { key: 'search', href: '/', label: '검색' },
  { key: 'recent', href: '/properties/recent', label: '최근 본 물건' },
  { key: 'favorites', href: '/favorites', label: '관심물건' },
  // 2026-08-11 Sprint 54 — 마이페이지. 비로그인 상태에서도 메뉴는 노출하고
  // 클릭 시 로그인으로 유도한다(docs/FRONTEND_MASTER_SPEC.md §7.2와 동일한 규칙).
  { key: 'mypage', href: '/mypage', label: '마이페이지' },
]

// properties/page.tsx의 검색/최근 본 물건 링크 스타일을 그대로 재사용해 세 화면(검색/최근 본
// 물건/관심물건)이 서로 이동 가능하도록 공유하는 nav. 새 스타일을 만들지 않고 기존
// "text-xs text-blue-500 font-medium" 링크 스타일을 그대로 쓰고, 현재 페이지만 다른
// 페이지 제목에 쓰이는 "text-gray-900 font-bold" 조합으로 구분한다.
export default function PrimaryNav({ current }: PrimaryNavProps) {
  // 스크린리더가 주요 메뉴 영역으로 건너뛸 수 있도록 nav 랜드마크를 쓴다
  // (Sprint 47 접근성 감사: 문서에 nav 랜드마크가 0개였다).
  return (
    // `flex-wrap`: 좁은 화면(320px)이나 브라우저 글자 확대에서 메뉴 4개가 한 줄에
    // 들어가지 않을 때 접히게 한다. 접히지 않으면 화면 전체가 가로로 스크롤된다
    // (2026-08-21 Sprint 240 실측 — SiteHeader.tsx 주석 참고).
    // 간격(gap-3)·글자크기(text-xs)·색은 그대로다.
    <nav aria-label="주요 메뉴" className="flex flex-wrap items-center gap-3">
      {NAV_ITEMS.map((item) => (
        <Link
          key={item.key}
          href={item.href}
          aria-current={current === item.key ? 'page' : undefined}
          className={
            current === item.key
              ? 'text-xs text-gray-900 font-bold'
              : 'text-xs text-blue-500 font-medium'
          }
        >
          {item.label}
        </Link>
      ))}
    </nav>
  )
}
