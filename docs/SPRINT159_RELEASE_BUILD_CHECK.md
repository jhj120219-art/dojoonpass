# Sprint 159 — 배포 빌드에 `localhost`가 굳는 문제와 점검 도구

작성 2026-08-17. 모든 수치는 실행 결과다. 공유 문서는 다른 세션이 편집 중이라 건드리지 않았다.

---

## 1. E2E부터 확인했다 (결함 없음)

실행 중인 서버에 사용자 흐름 전체를 태웠다.

```
검색 API        200  total=9  items=9        21ms
검색 화면(SSR)  200  63,903 bytes            29ms
   상세 링크 9개(고유 9개) · <img> 9개 · loading=lazy 9개
   실데이터 렌더 확인: "타경" 18회 / "유찰" 38회 / "감정가" 20회 / "법원" 23회

물건별 이미지   9/9 성공 (0.91 MB, 전부 ETag 부여됨)
물건별 문서     3/9 보유 (505·502 = SPEC+STATUS+APPRAISAL, 11853 = STATUS)
```

> 자기 정정: 처음 측정에서 "상세 링크 0개"가 나와 내비게이션이 깨진 줄 알았다.
> **내 정규식이 틀린 것이었다** — 실제 href는 `/properties/505?ids=505,1533,...`처럼
> 쿼리스트링이 붙는데 `href="(/properties/\d+)"`로 닫는 따옴표를 강제했다.
> 고쳐서 다시 세니 9개 전부 있었다. 결함으로 보고하지 않았다.

## 2. 그러다 본 것 — 이미지 주소가 절대 URL이다

```html
<img loading="lazy" src="http://localhost:8000/api/v1/item/505/images/1">
```

추적해 보니 설정 가능한 구조였다(**하드코딩 아님**).

```
src/lib/api.ts:5
export const API_BASE_URL =
    process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
```

`.env.local`에 값이 정의돼 있다(값은 출력하지 않았다). **지금 상태는 정상이다.**

## 3. 그런데 실패 모드가 고약하다

`NEXT_PUBLIC_*`는 **빌드 시점에 번들에 그대로 박힌다**(런타임에 읽지 않는다).
배포 빌드를 만들 때 이 변수를 빠뜨리면 fallback이 굳어 버리고, 사용자의 브라우저는
**자기 PC의 8000 포트**로 이미지·문서·API를 요청한다.

```
이미지가 안 뜬다        사용자 PC에는 서버가 없으므로
문서 뷰어가 빈 화면      HEAD 요청이 실패
오류 메시지는 없다       네트워크 실패라 화면이 그냥 비어 있다
```

이 저장소가 반복해 없애 온 **"조용한 실패"** 와 같은 모양이고, 하필 배포 직후에만 드러난다.

**실측**: 현재 production 산출물(`.next/server`, `.next/static`) 218개 파일 중
**5개에 `http://localhost:8000`이 박혀 있다.** 로컬 빌드이므로 정상이지만,
같은 방식으로 배포 빌드를 만들면 그대로 나간다.

검사하는 곳이 없었다.

```
테스트         NEXT_PUBLIC_API_BASE_URL 를 검사하는 곳 0건
릴리스 체크리스트  언급 0건
```

## 4. `check_release_build.py` (신규, 읽기 전용)

```
python check_release_build.py                # 보고만 (exit 0)
python check_release_build.py --production   # fallback 이 박혀 있으면 exit 1
```

기본 동작을 "보고만"으로 둔 이유: 로컬 개발 빌드에는 당연히 localhost가 들어 있다.
개발자의 정상 작업을 막지 않되, 배포 파이프라인에서는 `--production`으로 차단한다.

### 오탐을 없애는 것이 설계의 핵심이었다

첫 버전은 "아무 localhost"를 잡았고 곧바로 **오탐투성이**가 됐다.

```
http://localhost:9999   Supabase auth-js 의 기본값
http://localhost:3000   Next dist/client 내부
http://localhost        Next 내부
```

전부 라이브러리가 자기 기본값으로 들고 있는 문자열이라 우리 설정과 무관하고
**어떤 빌드에도 들어간다.** 이걸 "배포 불가"로 보고하면 검사는 곧 무시당한다.

경로로 걸러 보려 했지만 Next는 node_modules를 `[root-of-the-server]__*.js` 같은
청크에 **함께 묶어** 버려 경로만으로는 구분되지 않았다(실측으로 실패 확인).

→ 그래서 **`api.ts`에서 fallback 문자열을 읽어** 정확히 그것만 본다.
fallback을 바꾸면 검사도 따라온다. 나머지 주소는 "정보"로만 표시한다.

`.next/dev`(개발 서버 전용, 배포되지 않음)와 `.next/server`·`static`(배포 산출물)도
구분한다 — dev만 있으면 "배포 빌드가 아니다"라고 알린다.

### 검사가 비어 있지 않다는 증명

합성 빌드 세 개로 확인했다(전체 재빌드 없이 스캔 로직만 검증 — 이 점은 명시해 둔다).

```
1) fallback 이 박힌 빌드   -> 차단 대상 True   (2개 파일 탐지)
2) 실주소로 빌드된 상태     -> 차단 대상 False  (통과)
3) 라이브러리 기본값만      -> 차단 대상 False  (오탐 없음, 정보로만 표시)
```

통과와 실패 **양쪽**을 구분한다.

## 5. ★ 내가 만든 파일이 기존 검사를 깼다 (그리고 고쳤다)

`check_release_build.py`를 만든 직후 전체를 돌리니 **실패가 1건에서 2건으로 늘었다.**

```
[FAIL] cp949로 못 내보내는 출력 리터럴 없음:
       ['check_release_build.py:196 U+2014', ... 6곳]
```

`test_console_encoding.py`가 잡았다. 출력 문자열에 em dash(`—`, U+2014)를 썼는데
Windows 기본 콘솔(cp949)에서 인코딩할 수 없는 문자다. 내 `emit()`에 예외 대비가
있긴 하지만, 이 저장소의 규칙은 **애초에 출력 리터럴에 그런 문자를 두지 않는 것**이다.

한 번에 못 고쳤다 — 치환 스크립트가 `emit(`가 있는 줄만 봐서 **연속 줄에 걸친
문자열 리터럴 하나를 놓쳤다**(193행). 그래서 한 번 더 고쳤다.

```
수정 전   통과 35 | 실패 2      <- test_console_encoding.py 추가 실패
수정 후   통과 36 | 실패 1      <- 3회 연속 동일, test_console_encoding 단독 3/3 통과
```

> 중간에 "실패 2"를 관찰했으나 **불안정(flaky)이 아니다** — 연속 줄을 아직 못 고친
> 시점의 상태였다. 원인을 확인하지 않은 채 "가끔 그렇다"로 넘기지 않았다.

기존 검사가 내 실수를 잡아 준 사례라 그대로 기록해 둔다.

## 6. 검증 결과

```
파이썬 전체   통과 36 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 4,356건, 39.8s)  ×3회 동일
              실패 1건은 test_schema_hygiene.py — 이 변경과 무관
프런트엔드    exit 0 (111/111)
tsc 0   eslint 0   compileall 0
```

## 7. 변경 파일

```
신규   check_release_build.py                   배포 전 점검(읽기 전용, 빌드/배포 안 함)
신규   docs/SPRINT159_RELEASE_BUILD_CHECK.md
```

**프로덕션 코드 변경 0.**

## 8. 배포 담당자에게 (승인 영역이라 실행하지 않음)

배포 빌드를 만들기 **전에** `NEXT_PUBLIC_API_BASE_URL`을 실제 API 주소로 설정하고,
빌드 후 다음을 실행하면 fallback이 굳었는지 알 수 있다.

```
python check_release_build.py --production      # exit 1 이면 배포 중단
```

`docs/BETA_RELEASE_CHECKLIST.md`에 이 항목을 추가하는 것이 좋겠으나, 그 파일은
다른 세션이 편집 중이라 건드리지 않았다.
