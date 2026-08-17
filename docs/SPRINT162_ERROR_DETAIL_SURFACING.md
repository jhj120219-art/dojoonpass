# Sprint 162 — 서버가 알려 준 오류 사유를 화면이 버리고 있었다

작성 2026-08-17. 모든 수치는 실행 결과다. 공유 문서(`CURRENT_STATE.md`,
`BETA_RELEASE_CHECKLIST.md`)는 다른 세션이 편집 중이라 건드리지 않았다.

---

## 1. 프런트엔드 오류 처리를 훑다가 나왔다

먼저 정상 동작을 확인했다. 잘못된 검색 파라미터를 넣어도 화면은 죽지 않는다.

```
min_appraisal=<초대형>   API 400  ->  WEB 200 + 안내 + 복구 링크
page=99999999999999999999 API 400  ->  WEB 200 + 안내
sort_by=BOGUS            API 400  ->  WEB 200 + 안내
size=99999               API 422  ->  WEB 200 + 안내
```

내부 정보 노출도 없다(`Traceback` / `webpack` / `ApiError:` / stack 전부 0건).
**Sprint 51에서 만든 두 갈래 분기(`bad_request` vs `unavailable`)가 잘 동작한다.**

> 자기 정정: 처음에 `sido=없는지역` 이 WEB 400 + 0바이트라 결함인 줄 알았다.
> **URL 을 퍼센트 인코딩하지 않은 내 요청 문제**였다(브라우저는 항상 인코딩한다).
> 제대로 인코딩하니 API·WEB 모두 200이다. 결함으로 보고하지 않았다.

## 2. 그런데 안내 문구가 **엉뚱한 곳을 고치라고** 말한다

```
API :  {"detail":"허용되지 않는 sort_by 값입니다: BOGUS"}
화면:  "검색조건에 잘못된 값이 있습니다
        주소창의 검색조건 중 일부가 허용되지 않는 값입니다
        (페이지 번호는 1 이상, 한 페이지 개수는 1~100)."
```

백엔드는 **어느 조건이 왜 틀렸는지 정확히** 알려 주는데, 화면은 그 본문을 통째로
버리고 고정 문구를 띄운다. 그 고정 문구가 하필 페이지/개수만 언급해서,
`sort_by` 나 `min_appraisal` 이 틀린 사용자는 **멀쩡한 페이지 번호를 들여다보게 된다.**

원인은 한 줄이었다.

```ts
// src/lib/api.ts  (수정 전)
if (!res.ok) {
  throw new ApiError(res.status, `API 요청 실패 (${res.status}): ${path}`)
}   // <- 응답 본문을 읽지도 않는다
```

## 3. 수정 — 문자열일 때만 그대로 보여 준다

`ApiError` 에 선택적 `detail` 을 추가하고, 실패 응답에서 사유를 읽는다.

```ts
async function readDetail(res: Response): Promise<string | undefined> {
  try {
    const body = await res.json()
    return typeof body?.detail === 'string' ? body.detail : undefined
  } catch { return undefined }
}
```

**문자열일 때만** 담는 것이 핵심이다. FastAPI 검증 오류(`page=0`, `size=99999`)의
`detail` 은 영어 객체 **배열**이라 사용자에게 보여줄 것이 못 된다
(`{"type":"greater_than_equal","loc":["query","page"],"msg":"Input should be..."}`).
그때는 `undefined` 로 두고 기존 안내 문구로 떨어진다.

`SearchScreen.tsx` 는 사유가 있으면 그것을, 없으면 기존 문구를 보여 준다.
어느 쪽이든 복구 동선(`검색조건 초기화`)은 유지된다.

### 수정 후 실측 (실제 렌더된 텍스트)

```
?sort_by=BOGUS                 -> 허용되지 않는 sort_by 값입니다: BOGUS        + 검색조건 초기화
?min_appraisal=<초대형>         -> min_appraisal 값이 허용 범위를 벗어났습니다   + 검색조건 초기화
?page=0                        -> 주소창의 검색조건 중 일부가 ... (1~100)      + 검색조건 초기화
?size=99999                    -> 주소창의 검색조건 중 일부가 ... (1~100)      + 검색조건 초기화
```

**노출 안전성**: `bad_request` 분기는 400/422 에서만 탄다(500 은 `unavailable` 로 간다).
그 경로의 문자열 `detail` 은 전부 백엔드가 사용자에게 보여주려고 쓴 한국어 문구다.

## 4. ★ 처음 만든 회귀 테스트는 **비어 있었다**

테스트를 붙이고 mutation 을 돌렸더니 **그대로 통과했다.**

```
detail 전달 제거 -> 재빌드 -> 재기동 -> 113/113 pass, exit 0   ← 잡지 못했다
```

원인은 내 단언이었다.

```js
assert.ok(body.includes('sort_by'))   // <- 정렬 링크·검색 Form 에도 'sort_by' 가 있다
```

**필드명은 페이지 어디에나 있다.** 사유를 버려도 항상 참이 되는 단언이었다.
서버 문구 자체를 찾도록 바꾸고, "기본 안내가 사라졌는지"까지 함께 확인하게 했다.

```js
['?sort_by=BOGUS', '허용되지 않는 sort_by 값입니다']            // 서버 문구 그대로
assert.ok(!body.includes('주소창의 검색조건 중 일부가 ...'))     // 기본 안내가 대체됐는가
```

### 다시 mutation — 이번엔 잡힌다

```
detail 전달 제거 -> 재빌드 -> 재기동 -> 113 tests / 112 pass / 1 fail, exit 1
   AssertionError: ?sort_by=BOGUS: 서버가 준 사유("허용되지 않는 sort_by 값입니다")가
                   화면에 없습니다 — 응답 본문이 버려졌습니다
원복 후 재빌드 -> 113/113 pass, exit 0
```

> 이 절을 남기는 이유: 통과하는 테스트를 만드는 것과 **결함을 잡는 테스트를 만드는 것**은
> 다르다. mutation 을 돌리지 않았다면 "회귀 고정 완료"라고 적고 넘어갔을 것이다.

## 5. 검증 결과

```
파이썬 전체   통과 36 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 4,366건, 42.8s)
              실패 1건은 test_schema_hygiene.py — 미추적 파일 문제(이 변경과 무관)
프런트엔드    113 tests / 113 pass / 0 fail, exit 0   (111 -> 113, 신설 2건)
tsc 0   eslint 0   next build 성공
```

## 6. 곁가지 — 빌드가 EPERM 으로 실패했다 (환경 문제, 해결)

```
Error: EPERM: operation not permitted, unlink '.next\static\xGN_jQMQQ9CfRH_YBiH8D'
```

node 프로세스는 0개였고, 해당 경로는 **파일이 아니라 디렉터리**(옛 매니페스트 3개)였다.
OneDrive 동기화 폴더라 핸들이 남은 것으로 보인다. 그 디렉터리만 지우고 재빌드하니 성공했다.
`.next/` 는 빌드 산출물이자 `.gitignore` 대상이라 안전한 조작이다.
`/goal` 규칙대로 파일 lock 을 종료 사유로 쓰지 않았다.

## 7. 변경 파일

```
수정   src/lib/api.ts                    ApiError.detail + readDetail() (+근거 주석)
수정   src/app/search/SearchScreen.tsx   사유가 있으면 그것을, 없으면 기존 안내
수정   tests/frontend-contract.test.mjs  회귀 2건 (사유 노출 / 배열이면 기본 안내로 폴백)
신규   docs/SPRINT162_ERROR_DETAIL_SURFACING.md
```

`fetchJSON` 만 고쳤다 — `postJSON`/`deleteJSON`/`fetchAuthedJSON` 도 같은 구조지만
이번에 **실측으로 문제를 확인한 경로는 검색(GET)뿐**이라 거기까지만 바꿨다.
나머지는 호출부가 envelope 의 `error` 코드로 분기하므로 성격이 다르다(확인함).
