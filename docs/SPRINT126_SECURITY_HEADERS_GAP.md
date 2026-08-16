# Sprint 126 ― 응답 보안 헤더가 하나도 설정돼 있지 않다 (2026-08-15)

> 앞 Sprint: `docs/SPRINT125_NEXTJS_CVE_CORRECTION.md`
>
> **별도 파일 이유**: Sprint 100~125와 같다.

## 발견

`next.config.ts` 전문(6줄, `reactCompiler: true`뿐) + `src/` 전체를 확인한 결과
`headers()` 설정이 어디에도 없다. `grep -rn "X-Frame-Options\|Content-Security-Policy\|
Strict-Transport" src/` 결과 0건. `docs/BETA_RELEASE_CHECKLIST.md`/`docs/backend.md`도
CORS(`api_server.py`)만 언급하고 프런트 응답 헤더는 언급하지 않는다 ― 지금까지
어느 세션에서도 확인한 적이 없는 영역으로 보인다.

이 앱이 `<iframe>`을 쓰는 곳(`properties/[id]/page.tsx`)은 **이 앱이 자기 API를
안에 담는** 방향이라 `X-Frame-Options`(다른 사이트가 **이 앱을** 담는 것을 막는
헤더)와는 반대 방향이다 ― 충돌 없음을 확인했다.

## 왜 지금 구현하지 않는가

이 저장소의 확립된 관례를 그대로 따른다 ― `docs/CLAUDE.md` "최소 변경 원칙 - 요청된
기능만 수정"과 "Spec 변경 금지"(예: Sprint 121의 로그아웃 노출 위치 건과 같은 이유).
클릭재킹 방지(`X-Frame-Options: DENY` 또는 `frame-ancestors 'none'`) 자체는 이 앱에
낮은 위험으로 추가할 수 있을 것 같지만, **완전한 CSP는 이 앱이 실제로 불러오는 모든
출처(Supabase 프로젝트 URL, 폰트, 향후 추가될 분석 스크립트 등)를 전부 알아야
정책을 짤 수 있고, 잘못 짜면 로그인(Supabase Auth 리다이렉트)이나 API 호출 자체가
막혀 앱이 깨진다.** 이건 브라우저에서 실제로 검증해야 하는 UI 영향 변경이라
(`CLAUDE.md`: "UI 변경 시 브라우저에서 실제로 테스트") 이 세션에서 실행하지 않고
사실만 기록한다.

## 검증

| 항목 | 결과 |
|---|---|
| 보안 헤더 설정 존재 여부 | `grep` 확인 0건(신규 발견) |
| iframe 사용과의 충돌 여부 | 방향이 반대라 충돌 없음(자기 API를 담는 것, 남에게 담기는 것 아님) |
| 코드 변경 | 없음(발견 기록만) |

## 수정 파일

```
docs/SPRINT126_SECURITY_HEADERS_GAP.md   신규 (본 문서)
```

## SKIP (사용자/제품 결정 필요)

| 항목 | 이유 |
|---|---|
| `next.config.ts`에 보안 응답 헤더(`X-Frame-Options`/CSP/HSTS 등) 추가 | UI 영향 변경이라 브라우저 실측 검증 필요, 완전한 CSP는 허용 출처 목록 확정이 선행돼야 함(제품/인프라 지식 필요) - 승인 및 별도 세션에서 브라우저 QA와 함께 진행 권장 |

## 남은 Backlog

- Sprint 105~125의 SKIP 표 항목들 (전부 승인/외부 조치 대기, 미해소)
