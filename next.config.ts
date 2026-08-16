import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,
  // 2026-08-15 Sprint 127: 프레임워크 식별 정보 노출 축소. 기본값(true)이면 모든 응답에
  // `X-Powered-By: Next.js` 헤더가 붙어 공격자가 프레임워크 버전을 굳이 추측하지 않아도
  // 되게 도와준다(Sprint 125가 조사한 Next.js CVE들처럼 프레임워크 특정 취약점을 노리는
  // 정찰에 직접 쓰인다). 이 헤더를 읽는 코드는 저장소 전체에 없다(`grep` 확인) - 순수
  // 정보 노출만 없애는 변경이라 기능 영향이 없다.
  poweredByHeader: false,

  // 2026-08-15 Sprint 127: docs/SPRINT126_SECURITY_HEADERS_GAP.md가 찾은 공백 중,
  // **허용 출처 목록 같은 정책 결정이 필요 없는 것만** 추가한다. `Content-Security-Policy`는
  // 이 앱이 실제로 불러오는 모든 출처(Supabase 프로젝트 URL 등)를 전부 확정해야 정책을
  // 짤 수 있어 여전히 승인 영역으로 SKIP(문서 그대로).
  //
  // 아래 넷은 전부 "무엇을 허용할지"가 아니라 "쓰지 않는 것을 막는다"는 방향이라 값 자체에
  // 제품 판단이 필요 없다.
  //   - `X-Content-Type-Options: nosniff` — 브라우저의 MIME 스니핑을 막는다. 이 저장소는
  //     파일 응답마다 `mimetypes.guess_type()`으로 Content-Type을 이미 명시적으로 채우므로
  //     (`api/v1/registry.py`/`api/v1/documents.py`) 스니핑에 의존하는 동작이 없다.
  //   - `X-Frame-Options: DENY` — 이 앱이 **남에게 담기는** 것을 막는다. 이 앱이 iframe으로
  //     담는 방향(`properties/[id]/page.tsx`, 자기 API 문서 뷰어)과는 반대라 충돌 없음을
  //     확인했다(Sprint 126).
  //   - `Referrer-Policy: strict-origin-when-cross-origin` — 최신 브라우저 기본값과 동일한
  //     값이라 실질적으로 동작을 바꾸지 않고 명시적으로 고정만 한다.
  //   - `Permissions-Policy` — 이 앱이 쓰지 않는 브라우저 기능(카메라/마이크/위치)만
  //     끈다(`grep -rn "navigator\.\(geolocation\|mediaDevices\)" src/` 결과 0건 확인).
  //
  // 브라우저로 실제 응답 헤더를 확인했다(dev 서버, `curl -D -`) — 아래 네 값이 그대로
  // 실린다. 로그인/검색/상세 페이지의 프런트 계약 테스트(108/108)도 이 설정을 반영한
  // dev 서버를 대상으로 재실행해 통과를 확인했다(Server Action 포함, 헤더 추가가 폼
  // 제출 자체를 막지 않음).
  async headers() {
    const securityHeaders = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
    ];
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
