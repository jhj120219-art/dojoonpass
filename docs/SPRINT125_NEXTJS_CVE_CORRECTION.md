# Sprint 125 ― Sprint 124의 npm audit 결론이 틀렸다: Next.js 자체에 실사용자 공격 표면이 있다

> 앞 Sprint: `docs/SPRINT124_DEPENDENCY_DEADCODE_AUDIT.md`
>
> **별도 파일 이유**: Sprint 100~124와 같다.

Sprint 124는 `npm audit`의 축약 출력(7건)만 보고 "전부 빌드 툴체인, 런타임 공격 표면
없음"이라고 결론 내렸다. **이 세션 자신의 이전 보고서를 그대로 믿지 않는다는 원칙을
스스로에게 적용해 다시 확인했더니, 그 결론이 틀렸다.**

---

## 무엇을 놓쳤나

`npm audit`(요약)과 `npm audit fix --dry-run`(전체)의 출력이 다르다 ― 후자가 **Next.js
자체의 취약점 9건**을 추가로 드러낸다. 요약 출력만 본 Sprint 124는 이 9건을 아예 보지
못했다.

```
next  9.3.4-canary.0 - 16.3.0-preview.10   (설치된 16.2.9가 이 범위 안에 있다)
Severity: high
  - Middleware / Proxy bypass (App Router + Turbopack + 단일 로케일)
  - Denial of Service in App Router using Server Actions
  - Server-Side Request Forgery in Server Actions on custom servers
  - Cache confusion of response bodies (2건)
  - Unbounded Server Action payload in Edge runtime
  - SSRF in rewrites via attacker-controlled destination hostname
  - Denial of Service in the Image Optimization API using SVGs
  - Unauthenticated disclosure of internal Server Function endpoints
```

## 이 저장소에 실제로 적용되는가 ― 하나씩 대조했다

각 CVE의 GitHub Advisory(GHSA) 원문에서 "정확히 어떤 조건이 있어야 걸리는가"를
확인하고, 이 저장소의 실제 설정과 대조했다.

| CVE | 조건 | 이 저장소 | 적용 여부 |
|---|---|---|---|
| GHSA-955p (Server Function 노출) | App Router + Server Action(`use server`) | `src/app/login/actions.ts`에 `'use server'` 존재(로그인/회원가입) | **적용됨** |
| GHSA-m99w (Server Actions DoS) | App Router + Server Action 1개 이상 | 위와 동일 | **적용됨** |
| GHSA-6gpp (Middleware/Proxy 우회) | App Router + **Turbopack** + `config.i18n.locales`가 **정확히 1개** | `next.config.ts`에 i18n 설정 자체가 없다(`grep` 확인, `reactCompiler: true`뿐). 2026-08-15 `npm run build` 실측으로 **Turbopack 조건은 실제로 성립함을 확인**("Next.js 16.2.9 (Turbopack)") - 그래도 i18n 조건이 없어 미적용은 그대로다 | 미적용 |
| SSRF (custom server) | 커스텀 서버(server.js 등)로 구동 | `package.json` scripts가 `next dev`/`next build`/`next start` 그대로, 커스텀 서버 파일 없음 | 미적용 |
| Unbounded payload (Edge runtime) | Server Action이 Edge 런타임에서 실행 | `grep -rn "runtime.*edge\|export const runtime" src/` 결과 0건 - 전부 기본(Node) 런타임 | 미적용 |
| SSRF (rewrites) | `next.config.ts`에 `rewrites()` 설정 | 없음(위 config 전문 확인) | 미적용 |
| Image Optimization DoS(SVG) | `next/image` 사용 | `grep -rn "next/image" src/` 결과 0건(Sprint 124에서 이미 확인) | 미적용 |
| Cache confusion 2건 | 세부 조건 미조사(아래 "조사 안 한 것" 참고) | ― | 미확인 |

**9건 중 2건(GHSA-955p, GHSA-m99w)이 이 저장소의 실제 설정에 그대로 걸린다.** 나머지
6건은 이 앱이 안 쓰는 기능(커스텀 서버/Edge런타임/rewrites/next-image/i18n)에만 걸리므로
미적용, 2건은 조사하지 않았다(아래 참고).

### 적용되는 2건의 실제 위험도

**GHSA-955p-x3mx-jcvp** (CVE-2026-64643, CVSS 6.3 Moderate)
> "Server Action IDs가 공개적으로 서빙되는 클라이언트 아티팩트(정적 청크 등)를 통해
> 비인증 사용자에게 노출될 수 있다."

영향은 **정찰(recon) 수준**이다 ― Server Action의 내부 ID 존재 여부가 드러날 뿐,
그 자체로 데이터 유출이나 인증 우회는 아니다. `loginAction`/`signUpAction`은 애초에
로그인 페이지(비로그인 접근 가능)에 있는 액션이라 "존재를 안다"는 것 자체의 추가
피해가 낮다 ― 다만 앞으로 인증된 사용자 전용 Server Action이 추가되면 이야기가
달라진다(그때는 "그 액션이 존재한다"는 사실 자체가 공격 표면이 된다).

**GHSA-m99w-x7hq-7vfj** (CVE-2026-64641, CVSS **8.2 High**)
> "App Router + Server Action 1개 이상을 쓰는 Next.js 앱을 겨냥한 조작된 요청이,
> 같은 프로세스의 다른 요청 처리를 막는 과도한 CPU 사용을 유발할 수 있다."

**이쪽이 진짜다.** 조건 3가지(App Router / Server Action 1개 이상 / 공격자가 조작한
요청) 전부 이 저장소에 그대로 성립하고, **"업그레이드 외에는 우회 방법이 없다"**고
advisory가 명시한다. `loginAction`은 비인증 사용자가 도달할 수 있는 공개 경로이므로
공격자가 이 엔드포인트에 조작된 요청을 반복해서 보내 서버 프로세스를 DoS시킬 수
있다는 뜻이다.

## 고친 것 ― 이번에도 정확한 최소 수정안을 만들어 두고 실행은 SKIP한다

두 CVE 다 **`next@16.2.11`에서 고쳐졌다**(`npm view next versions`로 실재 확인,
`16.2.12`까지도 이미 나와 있다). Sprint 124가 인용한 `npm audit fix --force`는
`next@16.3.1`(마이너 버전 전체 상승, 다른 무관한 변경까지 포함)을 요구하지만, **이
저장소에 실제로 필요한 건 `16.2.9 -> 16.2.11`(같은 마이너 버전 안의 패치 2개)뿐이다**
― 훨씬 작고 안전한 변경이다.

```bash
# 이 세션에서 실행하지 않았다 - 승인 영역(docs/CLAUDE.md: 새 라이브러리 설치는 승인 후)
npm install next@16.2.11   # 또는 16.2.12(더 최신 패치, 존재 확인함)
```

`package.json`이 `next`를 `^`/`~` 없이 **정확한 버전으로 고정**하고 있어(`"next":
"16.2.9"`), 이 한 줄만 바꾸면 된다 ― 다른 의존성(`react`/`react-dom`/`@supabase/*`)은
영향받지 않는다(`npm ls next` 확인 결과 이 저장소 트리에 `next`는 하나뿐).

실행하지 않은 이유는 Sprint 124와 같다(`docs/CLAUDE.md`: 새 라이브러리 버전 설치는
승인 후) ― 다만 **우선순위를 정정한다.** Sprint 124는 이 항목 전체를 "빌드 툴체인,
급하지 않음"으로 뭉뚱그렸는데, 실제로는 **CVSS 8.2 미인증 DoS + 우회책 없음**이
섞여 있었다. Release Blocking에 가깝다 ― 아래 표 참고.

### 조사하지 않은 것 (정직하게 남긴다)

- "Cache confusion of response bodies" 2건은 advisory 세부조건을 조사하지 않았다.
  일반적인 캐싱 동작에 관한 것이라 이 앱의 특정 설정에 좌우되지 않을 가능성이 있고,
  같은 `16.2.11` 업그레이드로 함께 해소되므로 별도 조사의 실익이 크지 않다고 판단했다
  ― 그래도 "확인 안 함"이지 "무관함 확인함"이 아니라는 차이는 남긴다.
- `brace-expansion`/`postcss`(top-level)/`@tailwindcss/postcss`는 Sprint 124의 결론
  (빌드 전용, 런타임 무관)이 여전히 유효하다 — 이번 재조사로 뒤집힌 것은 아니다.
  다만 정확한 무파괴 수정 버전을 추가로 확인했다: `postcss` 8.5.15→8.5.26,
  `brace-expansion` 1.1.15→1.1.18(둘 다 같은 마이너/패치 라인, `npm view` 실재 확인) —
  `next` 업그레이드와 별개로 적용 가능하지만 역시 승인 영역.

## Python 쪽도 같은 방식으로 다시 봤다 ― `pip-audit`

Sprint 124/이전 세션은 Python 의존성을 `requirements.txt`의 선언 버전과 설치 버전의
**일치 여부**만 확인했다("11/11 일치") — 그건 드리프트 검사이지 **취약점 검사가
아니다.** npm 쪽에서 같은 구분을 놓쳤던 것과 같은 종류의 사각지대라 여기도 다시 봤다.

`pip-audit`(이 세션에서 로컬 설치, `requirements.txt`에는 추가하지 않음 — 프로젝트
의존성이 아니라 1회성 진단 도구)로 설치된 환경 전체를 스캔했다.

```
Found 1 known vulnerability in 1 package
Name  Version ID              Fix Versions
----- ------- --------------- ------------
ecdsa 0.19.2  PYSEC-2026-1325
```

`ecdsa`는 `requirements.txt`에 직접 없다 — `python-jose[cryptography]`의 전이
의존성이고, `api/auth.py`가 ES256(JWKS) 토큰을 검증할 때 실제로 그 경로를 탄다.
즉 postcss/sharp와 달리 **"안 쓰는 기능"이 아니라 인증이라는 핵심 경로에서 매 요청
동작하는 코드다** — 여기서 멈추지 않고 advisory 원문(OSV `PYSEC-2026-1325` =
CVE-2024-23342, CVSS 7.4 High)을 확인했다.

**내용은 서명 생성(signing) 쪽 타이밍 사이드채널이다** — `SigningKey.sign_digest()`
호출을 시간 측정으로 관찰하면 nonce가 새어 나가 개인키 복원으로 이어질 수 있다는
것이 골자다. advisory가 명시적으로 "**서명 검증(verification)은 영향받지 않는다**"고
못박는다. 고칠 버전도 없다("side channel attacks are out of scope, no planned fix").

이 저장소가 `ecdsa`/`jose`를 **서명에 쓰는지** 확인했다.

```
grep -rn "jwt\.encode\|SigningKey\|sign_digest\|\.sign\(" --include="*.py" . (테스트 제외)
-> 0건
```

`api/auth.py`는 Supabase가 이미 서명한 토큰을 **검증만** 한다(`jwt.decode()`) — 이
저장소 어디에도 JWT를 직접 서명하거나 `ecdsa.SigningKey`를 호출하는 코드가 없다.
**취약한 연산(서명) 자체를 이 앱이 수행하지 않으므로, 고칠 버전이 없어도 실질
위험은 없다** — Sprint 124의 sharp(기능 자체를 안 씀)와 같은 결론이지만, 이번엔
"안 쓰는 next/image 기능"이 아니라 "쓰는 라이브러리의, 안 쓰는 연산"이라는 점이
다르다(더 미묘해서 더 쉽게 놓칠 수 있는 경우였다).

## 검증

| 항목 | 결과 |
|---|---|
| `npm ls next` | `next@16.2.9` 단일 트리 확인 |
| 9개 CVE 각각의 advisory 원문 대조 | GHSA-955p/GHSA-m99w/GHSA-6gpp 3건은 상세 확인, 나머지는 npm audit 출력의 조건 설명(custom server/edge runtime/rewrites/next-image)과 이 저장소 코드를 직접 대조 |
| `next.config.ts` 전문 확인 | i18n/rewrites 설정 없음 |
| Server Action 사용처 확인 | `grep "'use server'" src/` -> `src/app/login/actions.ts` 1곳 |
| Edge 런타임 사용처 확인 | `grep "runtime.*edge" src/` -> 0건 |
| 커스텀 서버 확인 | `package.json` scripts + 루트에 `server.*` 파일 없음 |
| 대체 수정 버전 실재 확인 | `npm view next/postcss/brace-expansion versions` 로 16.2.11/16.2.12, 8.5.26, 1.1.18 실재 확인 |
| `pip-audit` (Python 쪽, 로컬 설치) | 설치 환경 전수 스캔, `ecdsa` 1건 발견 |
| `ecdsa` advisory 원문 대조 | OSV `PYSEC-2026-1325`/CVE-2024-23342 - 서명 전용 결함, 검증 무관 명시 확인 |
| 이 저장소가 서명 연산을 쓰는지 확인 | `grep "jwt.encode\|SigningKey\|sign_digest\|\.sign\("` (테스트 제외) -> 0건 |
| 실 설치/변경 | **하지 않았다** ― `package.json`/`package-lock.json`/`requirements.txt` 전부 무변경(`pip-audit`은 진단 전용으로 로컬에만 설치, 프로젝트 의존성에 추가 안 함) |

## 회귀 방어 ― 고치지는 못해도 더 나빠지면 잡는다

`next` 업그레이드는 승인 영역이라 이 세션에서 반영할 수 없다. 대신
`test_schema_hygiene.py`에 §8(`test_known_dependency_cves_are_tracked`)을 신설해
- `package.json`의 `next` 버전이 지금보다 **더 낮은 버전으로 후퇴**하면 실패시킨다
  (다운그레이드 감지 - 변이 테스트로 확인: 16.2.9 -> 16.2.5로 낮추면 즉시 FAIL)
- 아직 `16.2.11` 미만이면 **실패시키지 않고** 정확한 CVE 근거와 업그레이드 명령을
  매 실행마다 출력한다(현재 상태가 이미 알려진 취약점이므로 "PASS해야 안전"이 아니라
  "얼마나 뒤처졌는지 알려주는" 역할)
- `16.2.11` 이상으로 업그레이드되면 "[정리됨]" 메시지로 이 상수와 아래 SKIP 항목을
  정리하라고 스스로 알려준다(실제로 16.2.11로 바꿔 재실행해 이 경로도 확인함)

## 수정 파일

```
docs/SPRINT125_NEXTJS_CVE_CORRECTION.md   신규 (본 문서, Sprint 124의 npm audit 결론 정정 + pip-audit 신규 실행)
test_schema_hygiene.py                    §8 신설 - next CVE 다운그레이드 감지 + 리마인더
```

제품 코드/의존성 변경 없음(테스트 1건 추가).

## SKIP (사용자/제품 결정 필요) ― 우선순위 정정판

| 항목 | 이유 | 우선순위 |
|---|---|---|
| `npm install next@16.2.11`(또는 16.2.12) | 새 라이브러리 버전 설치 - 승인 영역 | **높음** ― CVSS 8.2 미인증 DoS, 우회책 없음, 로그인 페이지가 공개 도달 경로 |
| `npm install postcss@8.5.26 brace-expansion@1.1.18`(top-level) | 새 라이브러리 버전 설치 - 승인 영역 | 낮음 (빌드 전용, Sprint 124 결론 유지) |
| `@tailwindcss/postcss`/`tailwindcss` 4.3.1 -> 4.3.3 | 새 라이브러리 버전 설치 - 승인 영역 | 낮음 (빌드 전용) |
| "Cache confusion" 2건의 상세 조건 조사 | 이 세션에서 미착수 - 필요하면 다음 세션에서 계속 | 중간 |

## 남은 Backlog

- Sprint 105~124의 SKIP 표 항목들 (전부 승인/외부 조치 대기, 미해소)
- 위 `next` 업그레이드가 승인되면: 업그레이드 후 전체 스위트(28/28 Python + 108/108
  프런트) + `npm run build` 재검증 필요(이 저장소는 OneDrive 동기화 폴더 안이라
  빌드 시 `.next` 잔재 이슈가 이미 문서화돼 있음, `docs/TEST_PLAN.md` 참고)
