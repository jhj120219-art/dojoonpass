import Link from 'next/link'
import SiteHeader from '@/components/SiteHeader'

// Next.js App Router 규약 파일 — 존재하지 않는 경로로 들어오면 기본(스타일 없는) 404 대신
// 이 화면을 보여준다. src/app/error.tsx와 같은 이유로 신설한다(2026-08-22).
export default function NotFound() {
  return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader />
      <main className="flex flex-col items-center justify-center py-20 gap-1">
        <p className="text-gray-500">페이지를 찾을 수 없습니다</p>
        <Link href="/" className="mt-4 rounded-xl bg-gray-100 px-4 py-2 text-sm font-medium text-gray-600">
          검색 화면으로
        </Link>
      </main>
    </div>
  )
}
