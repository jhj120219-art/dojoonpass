'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import PrimaryNav, { type PrimaryNavCurrent } from './PrimaryNav'
import LogoutButton from '@/app/properties/LogoutButton'
import TextSizeToggle from './TextSizeToggle'
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
    let cancelled = false
    // supabase-js는 이 effect 시점에 비로소 받아온다(`createClient()`가 Promise를 준다) —
    // 이유는 `@/lib/supabaseClient` 주석 참고. effect는 hydration 직후에 돌기 때문에
    // 청크 요청은 여기서 바로 시작되고, 화면 렌더/hydration을 막지 않는다.
    let unsubscribe: (() => void) | null = null
    createClient()
      .then((supabase) => {
        if (cancelled) return
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
        unsubscribe = () => sub.subscription.unsubscribe()
      })
      .catch(() => {
        // 세션 확인에 실패하면 로그인/로그아웃 어느 쪽도 그리지 않는다 — 이 컴포넌트가
        // 원래부터 갖고 있던 실패 동작 그대로다(getSession()이 거절되면 authChecked가
        // false로 남는다). 여기서 임의로 '로그인'을 띄우면 로그인한 사용자에게 로그아웃된
        // 것처럼 보이게 만드는 새 동작이 된다. 처리되지 않은 rejection만 삼킨다.
      })
    return () => {
      cancelled = true
      unsubscribe?.()
    }
  }, [])

  return (
    <header className="bg-white border-b border-gray-100">
      {/* ★ `flex-wrap` — 좁은 화면에서 헤더가 페이지를 가로로 밀어내지 않게 한다
          (2026-08-21 Sprint 240).

          실측(실제 320px 창, **로그인 상태**): 오른쪽 묶음(검색·최근 본 물건·관심물건·
          마이페이지·로그아웃)이 276px 인데 CONTAINER 안쪽 가용 폭은 257px 다.
          `shrink-0` 이라 줄어들지도 않아 오른쪽 끝이 308px -> 뷰포트 289px 를 넘고,
          `documentElement.scrollWidth > clientWidth` 가 되어 **모든 화면이** 가로로
          스크롤됐다(헤더는 전 화면 공용이다). 비로그인일 때는 '로그인' 한 줄이라
          219px 로 들어가서 — 그동안 로그아웃 상태로만 보면 멀쩡해 보였다.

          고치는 방식은 **줄바꿈 허용뿐**이다. 색·글자크기·간격(gap)은 하나도 바꾸지
          않는다(제품 디자인 결정은 승인 영역). 한 줄에 들어가는 폭에서는 wrap 이
          발동하지 않으므로 360/390/430px 및 데스크톱 렌더는 그대로다 — 재측정으로 확인. */}
      <div className={`${CONTAINER} py-4 flex flex-wrap items-center justify-between gap-4`}>
        <div className="flex items-baseline gap-3 min-w-0">
          <Link href="/" className="text-lg font-bold text-gray-900 shrink-0">
            콕찰
          </Link>
          {/* 화면의 대표 제목은 h1이어야 한다. Sprint 44에서 공통 Header를 만들며 각 페이지의
              <h1>을 이 자리로 옮기면서 span으로 바꿔버려, 문서에 h1이 하나도 없는 상태가 됐다
              (Sprint 47 접근성 감사에서 발견). 시각적 크기는 그대로 두고 시맨틱만 복구한다. */}
          {title && <h1 className="text-sm font-normal text-gray-400 truncate hidden sm:block">{title}</h1>}
        </div>
        {/* `shrink-0` -> `min-w-0` + `flex-wrap`: 이 묶음 자체도 줄어들고 접힐 수 있어야
            한다. `shrink-0` 이면 CONTAINER 보다 넓어도 그대로 버텨 페이지를 밀어낸다.
            `justify-end` 는 접혔을 때도 지금처럼 오른쪽 정렬을 유지하기 위한 것이다
            (한 줄에 들어갈 때는 바깥 `justify-between` 이 이미 오른쪽에 붙이므로 변화 없음). */}
        <div className="flex flex-wrap items-center justify-end gap-3 min-w-0">
          {/* 큰글씨 토글은 **모든 화면**에 있어야 한다 — 목록에서 켠 크기가 상세로
              넘어가면 그 화면에서도 끌 수 있어야 하고, 헤더는 8개 화면이 공유하는
              유일한 자리다(Master Spec §5.3). 새 화면이 생겨도 자동으로 따라간다. */}
          <TextSizeToggle />
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
