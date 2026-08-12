'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import PrimaryNav, { type PrimaryNavCurrent } from './PrimaryNav'
import LogoutButton from '@/app/properties/LogoutButton'
import { createClient } from '@/lib/supabaseClient'
import { CONTAINER } from '@/lib/layout'

type SiteHeaderProps = {
  current?: PrimaryNavCurrent
  title?: string
}

// docs/FRONTEND_MASTER_SPEC.md §5.3 — 모든 주요 화면이 공유하는 단일 Header.
// 배경(흰 바탕 + 하단 보더)은 화면 폭 전체로 깔고, 내부 콘텐츠만 본문과 동일한
// CONTAINER에 정렬한다(헤더 좌측 끝과 본문 좌측 끝이 한 줄로 맞아야 함).
//
// Navigation/로그아웃은 새로 만들지 않고 기존 PrimaryNav/LogoutButton을 그대로 조합한다
// (Master Spec §11.2 "동일 기능의 중복 컴포넌트를 만들지 않는다").
//
// 세션 확인을 서버가 아니라 클라이언트에서 하는 이유: 이 Header를 쓰는 화면 중
// /favorites·/properties/recent는 클라이언트 컴포넌트라 서버 세션을 prop으로 내려줄 수
// 없다. 한 곳에서만 세션을 읽도록 클라이언트 기준으로 통일했다.
export default function SiteHeader({ current, title }: SiteHeaderProps) {
  const [email, setEmail] = useState<string | null>(null)
  // 확인 전에는 로그인/로그아웃 어느 쪽도 그리지 않는다 — 잠깐 "로그인"이 보였다가
  // 이메일로 바뀌면 로그인 상태인데도 로그아웃된 것처럼 보이는 깜빡임이 생긴다.
  const [authChecked, setAuthChecked] = useState(false)

  useEffect(() => {
    const supabase = createClient()
    let cancelled = false
    // getSession()으로 충분하다. src/proxy.ts가 모든 요청에서 getUser()로 세션을 서버 검증하고
    // 쿠키를 갱신한 뒤에 이 페이지가 렌더되므로, 여기서 읽는 쿠키는 이미 신선하다.
    // 헤더에서 getUser()를 또 부르면 로그인 사용자의 매 페이지 로드에 Supabase 왕복이
    // 한 번씩 더 붙을 뿐 얻는 정확도가 없다.
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (cancelled) return
      setEmail(session?.user?.email ?? null)
      setAuthChecked(true)
    })
    // 로그인/로그아웃이 다른 화면에서 일어나도 Header가 즉시 따라가도록 구독한다.
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      if (cancelled) return
      setEmail(session?.user?.email ?? null)
      setAuthChecked(true)
    })
    return () => {
      cancelled = true
      sub.subscription.unsubscribe()
    }
  }, [])

  return (
    <header className="bg-white border-b border-gray-100">
      <div className={`${CONTAINER} py-4 flex items-center justify-between gap-4`}>
        <div className="flex items-baseline gap-3 min-w-0">
          <Link href="/" className="text-lg font-bold text-gray-900 shrink-0">
            콕찰
          </Link>
          {/* 화면의 대표 제목은 h1이어야 한다. Sprint 44에서 공통 Header를 만들며 각 페이지의
              <h1>을 이 자리로 옮기면서 span으로 바꿔버려, 문서에 h1이 하나도 없는 상태가 됐다
              (Sprint 47 접근성 감사에서 발견). 시각적 크기는 그대로 두고 시맨틱만 복구한다. */}
          {title && <h1 className="text-sm font-normal text-gray-400 truncate hidden sm:block">{title}</h1>}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <PrimaryNav current={current} />
          {authChecked &&
            (email ? (
              <>
                <span className="text-xs text-gray-400 hidden md:inline max-w-[180px] truncate">{email}</span>
                <LogoutButton />
              </>
            ) : (
              <Link href="/login" className="text-xs text-blue-500 font-medium">
                로그인
              </Link>
            ))}
        </div>
      </div>
    </header>
  )
}
