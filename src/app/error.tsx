'use client'

import Link from 'next/link'
import SiteHeader from '@/components/SiteHeader'

// Next.js App Router 규약 파일 — 이 트리 어디서든 렌더링 중 처리되지 않은 예외가 나면
// 기본(스타일 없는) 오류 화면 대신 이 화면을 보여준다. 지금까지 이 저장소에 이 파일이
// 없어서, fetch 실패처럼 각 페이지가 이미 잡고 있는 경우(예: properties/[id]/page.tsx의
// loadError)가 아니라 **예상치 못한 렌더링 예외**가 나면 사용자가 Next.js 기본 화면을
// 그대로 보게 돼 있었다(2026-08-22 실측 — src/app 전체에 error.tsx/not-found.tsx가
// 0개였다).
//
// 스타일은 이미 있는 관례(properties/[id]/page.tsx의 loadError 분기)를 그대로 재사용한다 —
// 새 디자인을 만들지 않는다.
export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader />
      <main className="flex flex-col items-center justify-center py-20 gap-1">
        <p className="text-gray-500 font-medium">문제가 발생했습니다</p>
        <p className="text-sm text-gray-500">일시적인 오류일 수 있습니다. 잠시 후 다시 시도해주세요</p>
        <div className="mt-4 flex gap-2">
          <button
            onClick={() => reset()}
            className="rounded-xl bg-gray-100 px-4 py-2 text-sm font-medium text-gray-600"
          >
            다시 시도
          </button>
          <Link href="/" className="rounded-xl bg-gray-100 px-4 py-2 text-sm font-medium text-gray-600">
            검색 화면으로
          </Link>
        </div>
      </main>
    </div>
  )
}
