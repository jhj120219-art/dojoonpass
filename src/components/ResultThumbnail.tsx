'use client'
import { useState } from 'react'
import { API_BASE_URL } from '@/lib/api'

/**
 * 목록 카드의 대표 사진 (2026-08-17 Sprint 145 / 2026-08-20 Sprint 224).
 *
 * ## 어느 화면이 쓰는가
 *
 * 검색목록 · 관심물건 · 최근 본 물건 — 셋 다 같은 컴포넌트를 쓴다.
 * 원래는 `src/app/search/` 안에 있었는데, 나머지 두 화면이 같은 사진을 보여 주게 되면서
 * `src/components/` 로 옮겼다. **화면마다 따로 만들면 규칙이 갈라진다** —
 * 한쪽만 `onError` 를 빠뜨리면 그 화면에서만 깨진 아이콘이 남고, 한쪽만 크기가 다르면
 * 같은 물건이 화면마다 달라 보인다.
 *
 * `url` 은 API 가 준 `thumbnail_url` 을 **그대로** 넘긴다(프런트에서 조립하지 않는다).
 * 경로 규칙의 유일한 출처는 백엔드 `api/v1/thumbnails.py` 다.
 *
 * ## 왜 별도 클라이언트 컴포넌트인가
 *
 * `ResultList.tsx`는 **서버 컴포넌트**다. 처음에는 그 안에 `<img onError=...>`를 직접
 * 넣었는데, Next.js가 런타임에 거부했다:
 *
 *     Event handlers cannot be passed to Client Component props.
 *     <img ... onError={function onError} ...>
 *
 * ★ 이 오류를 `tsc`/`eslint`/`next build` 셋 다 잡지 못했다 — 빌드는 통과하고 화면만
 *   죽는다. 실제로 브라우저로 열어 보고서야 발견했다.
 *
 * 사진이 깨졌을 때 자리를 숨기려면 `onError`가 필요하고, 이벤트 핸들러는 클라이언트
 * 컴포넌트에서만 쓸 수 있다. 그래서 **썸네일만** 작은 클라이언트 섬으로 떼어낸다
 * (같은 카드의 `FavoriteButton`이 이미 쓰는 방식과 같다). 목록 전체를 클라이언트로
 * 바꾸지 않으므로 나머지는 서버 렌더 그대로다.
 *
 * 깨진 경우 `<img>`를 지우고 빈 자리도 남기지 않는다 — 카드 레이아웃이 사진 없는
 * 물건과 같아진다(브라우저 기본 깨진 아이콘을 보여 주지 않는다).
 */
export default function ResultThumbnail({ url }: { url: string }) {
  const [broken, setBroken] = useState(false)
  if (broken) return null
  return (
    /* next/image를 쓰지 않는다(docs/SPRINT124 — 이 저장소는 이미지 최적화 파이프라인
       미사용). 목록은 스크롤로 내려가며 보므로 지연 로딩이 실제로 효과가 있다.
       alt=""+aria-hidden: 사진은 장식이고 물건 정보는 옆 텍스트가 모두 담고 있다. */
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`${API_BASE_URL}${url}`}
      alt=""
      aria-hidden="true"
      loading="lazy"
      onError={() => setBroken(true)}
      className="w-20 h-20 shrink-0 rounded-xl object-cover bg-gray-50 border border-gray-100"
    />
  )
}
