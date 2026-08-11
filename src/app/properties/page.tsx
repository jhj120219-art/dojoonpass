import { redirect } from 'next/navigation'

// ================================================================
// 레거시 `/properties` — 검색 첫 화면(`/`)으로 영구 이동
//
// 2026-08-11 Sprint 51. 이 화면은 프로토타입 시절의 잔재였고, 남겨두는 것이
// 사용자에게 **조용한 오답**을 보여주는 상태였다(`docs/BUGS.md` #34).
//
// 무엇이 문제였나
//  - 목록은 Supabase `properties` 테이블(시드 5행: "강남구 역삼동 아파트 / …123-45")을
//    직접 조회하면서, 카드 링크는 `/properties/{id}`(FastAPI `auction_item`)로 보냈다.
//    두 id 채번 체계가 달라 **404도 나지 않고 전혀 다른 물건이 열렸다** —
//    실측: "강남구 역삼동 아파트"를 누르면 "관악구 난곡로66가길 2층202호"가 열림
//  - `docs/CLAUDE.md`의 아키텍처 규칙("경매 데이터는 항상 Python API 경유,
//    Supabase에서 직접 조회하지 않는다")을 정면으로 위반하는 **유일한 화면**이었다
//  - Sprint 48·50 전수 조사 결과 저장소 안에 이 경로로 향하는 링크가 **0건**(고아 라우트).
//    `PrimaryNav`의 검색 링크·로그아웃 복귀·로그인 기본 복귀는 전부 `/`다
//
// 왜 redirect인가 (삭제도, 유지도 아닌)
//  - 북마크·외부 링크가 있을 수 있으므로 404를 새로 만들지 않는다
//  - `/`가 이미 같은 목적(경매 물건 목록)을 **정확한 데이터**로 수행한다
//  - 하위 경로 `/properties/[id]`·`/properties/recent`에는 영향이 없다
//    (Next.js는 더 구체적인 세그먼트를 먼저 매칭하고, 이 파일은 `/properties` 정확히 하나만 담당)
//  - `src/proxy.ts`의 `PROTECTED_PREFIXES`에 `/properties`가 그대로 있어 로그인 게이트도 유지된다
//
// 되돌리는 법: `git show <이 변경 이전 커밋>:src/app/properties/page.tsx`로 원본 구현을,
// 같은 방식으로 `src/app/properties/SearchFilters.tsx`를 복원하면 된다(둘 다 git 추적 중).
// 단 복원하더라도 위 id 채번 불일치는 그대로이므로 FastAPI 기반으로 다시 써야 한다.
// ================================================================
export default function LegacyPropertiesPage() {
  redirect('/')
}
