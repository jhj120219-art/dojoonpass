# Sprint 221 — 접속 정보 확인 · 접근성 구조 · 화면 전체 데이터 계약

2026-08-19. 기준 HEAD `73ac6eb`. **커밋/푸시 없음. 운영 DB 무변경. 화면 디자인 변경 없음.**

---

## 0. 개발 사이트 접속 정보 (BACKLOG 0)

세션 시작 시 **3000/8000 둘 다 비어 있었고** 관련 프로세스도 없었다.
코드 변경 없이 표준 명령으로 기동해 실제 응답을 확인했다.

```
WEB 접속 주소        http://localhost:3000/
API 주소             http://127.0.0.1:8000     (Swagger UI: /docs)
접속 상태            /        200   메인 = 검색 화면
                     /search  200
                     /login   200
                     /properties/{id}  307 -> /login   (로그인 게이트)
                     /api/v1/search    200
                     /docs             200
로그인 필요 여부      검색(`/`, `/search`)·로그인 화면은 **비로그인 접속 가능**
                     `/properties/*`, `/favorites`, `/mypage` 는 **로그인 필요**
                     (근거: `src/proxy.ts` `PROTECTED_PREFIXES`)
현재 화면            검색 폼 + 정렬 바 + "총 9건" + 결과 카드 9개,
                     각 카드에 대표 사진 썸네일이 실제로 렌더링됨(스크린샷 확인)
로컬 개발 서버 실행   터미널 2개로 아래를 각각 실행한다
                       python -m uvicorn api_server:app --host 127.0.0.1 --port 8000
                       npm run dev
                     API 주소는 `.env.local` 의 `NEXT_PUBLIC_API_BASE_URL` 이 정한다
                     (현재 `http://localhost:8000`).
```

**운영/외부 배포는 하지 않았다.** 전부 로컬이다.

★ 운영 메모: 긴 세션에서 `node` 프로세스가 누적되면 Turbopack 이
`0xc0000142` 로 죽어 dev 서버가 **500** 을 낸다(코드 결함 아님).
남은 node 프로세스를 모두 종료한 뒤 정상화된다 — 이번에 실제로 겪었다.

---

## 1. 접근성 구조 (BACKLOG 1) — 승인 없이 가능한 것만

색·크기·간격은 제품 결정이라 **건드리지 않았다.** 구조만 봤다.

### 실측 (실브라우저 `/`)

```
시맨틱 랜드마크        main 1 / nav 1 / header 1 / h1 1 / h2 1
접근 가능한 이름 없는 대화형 요소   0개
키보드로 갈 수 없는 클릭 요소       0개   (div/span 에 onClick 만 다는 패턴이 없다)
포커스 가능 요소                    53개
```

### 포커스 표시 — 문제 없다 (그리고 그 판정에 두 번 실패했다)

**결론**: 전역 리셋은 **없다.** 빌드 CSS 를 직접 확인했다.

```
.focus\:outline-none:focus                 { outline-style: none }
.focus-visible\:outline-none:focus-visible { outline-style: none }
:-moz-focusring                            { outline: auto }
```

`outline-style: none` 은 **그 유틸리티를 쓴 자리에서만** 나온다. 나머지 요소는
브라우저 기본 `:focus-visible` 링을 그대로 갖는다. 그 유틸리티를 쓰는 5곳은
**전부 대체 표시를 함께 갖고 있다**.

```
login/page.tsx x2            focus:border-blue-400          (테두리 색)
SearchForm.tsx               focus:ring-2 focus:ring-blue-200
SearchPresets.tsx            focus:ring-2 focus:ring-blue-200
SearchAccordionSection.tsx   focus-visible:ring-2 focus-visible:ring-blue-200
```

**★ 여기까지 오는 데 측정이 두 번 틀렸다.**

1. 계산된 스타일에서 `outline-style: none` 을 읽고 **"53개 전부 포커스 표시 없음"**
   이라고 판단할 뻔했다. 그것은 **비포커스 상태의 브라우저 기본값**이다
   (기본 `outline-style` 은 none, width 는 medium=3px).
2. `el.focus()` 로 강제 포커스한 뒤 다시 쟀는데도 0 이었다 —
   **프로그래밍 포커스는 Chrome 에서 `:focus-visible` 을 켜지 않는다.**

결국 **CSS 규칙 자체**를 읽어야 답이 나왔다.
계산된 스타일은 "지금 이 순간"만 말하고, 접근성은 **다른 순간의 규칙**에 달려 있다.

### 잠근 것

```
7. 포커스 표시를 지웠으면 반드시 대체(ring/border/shadow/bg)가 같은 className 에 있다
   + 전역 포커스 리셋이 없다 (빌드 CSS 를 검증된 검출기로 확인)
8. 랜드마크(main/nav/header/h1)가 사라지지 않는다 + 이름 없는 아이콘 버튼 0개
```

★ 이 가드도 두 번 틀렸다 —
`REPLACE` 패턴에 `outline-` 를 넣어 **`focus:outline-none` 자신이 자기 대체로** 잡혔고
(무엇을 지워도 통과했다), CSS 정규식이 `@supports` 블록을 선택자로 오인해
**변이를 넣지 않아도 항상 실패**했다. 둘 다 고친 뒤 변이로 재확인했다.
전역 리셋 검출기는 **넣기 전에** 검증했다 — 실제 0건 / 주입 시 1건 / 의도된 유틸리티 0건.

---

## 1-b. BUGS #149 — 모달이 모달이라고 말하지 않았다 (수정함)

전체 화면 오버레이 둘(문서 뷰어 / 사진 라이트박스)에 **`role="dialog"` 도
`aria-modal` 도 없었다**(저장소 전체 0건). 스크린리더는 그것이 모달인지 모르고,
**뒤의 검색 결과·가격·주소가 계속 읽힌다.**

`role`/`aria-modal`/`aria-labelledby` 는 **픽셀을 하나도 바꾸지 않는다** —
색·크기와 달리 제품 디자인 결정이 아니라서 그대로 고쳤다.

이미 있던 것(Escape 닫기, 좌우 화살표, 닫기 버튼 `aria-label`, 고정 height 없음)도
함께 회귀로 고정했다. **포커스 트랩은 여전히 없다** — Tab 이 배경으로 빠져나간다.
동작 변경 폭이 커서 별도 작업으로 남긴다.

변이 2종 검출(role 제거 / 없는 id 를 가리키는 `aria-labelledby`).

---

## 2. 화면 전체 데이터 계약 (BACKLOG 2 · 5)

목록 성격 화면 넷을 한 번에 대조했다. **어긋남 0.**

```
검색목록      API 19키 / 타입 19필드 / 렌더 17필드      어긋남 0
상세페이지     API 27키 / 렌더 20필드                   어긋남 0
관심물건      API 22필드(auction_item 21 + favorited_at) / 렌더 12   어긋남 0
최근 본 물건   API 22필드(+ viewed_at) / 렌더 12                      어긋남 0
```

관심물건·최근 본 물건은 `SELECT ai.*` 라 **계약이 스키마에 묶여 있다** —
컬럼 이름이 바뀌면 화면이 조용히 빈칸이 된다. 그래서 `auction_item` 의 실제 컬럼을
읽어 대조하도록 만들었다.

### ★ 발견 — 썸네일은 검색목록에만 있다

`thumbnail_url` 을 주는 API 는 `search.py` 하나뿐이고,
**관심물건·최근 본 물건 화면에는 `<img>` 가 아예 없다.**

```
사용자 흐름:  검색목록에서 사진을 보고 -> 관심물건에 담고 -> 관심물건에서 사진이 사라진다
```

기존 문서·결정 기록에 이에 대한 언급이 **없다**(Sprint 145 는 검색목록만 다뤘다).
즉 의도된 제외가 아니라 **미문서화 공백**으로 보인다.

**고치지 않았다** — API 응답 필드 추가 + 화면 레이아웃 변경이라 제품 디자인 결정이다.
구현 경로는 이미 있다: `search.py` 의 `SELECT item_id, MIN(seq) ... GROUP BY item_id`
배치 조회와 `ResultThumbnail` 컴포넌트를 그대로 재사용하면 된다.

대신 **규칙**을 걸었다 — *어느 화면이든 `thumbnail_url` 을 그리기 시작하면 그 화면의
API 도 그것을 주어야 한다.* 한쪽만 바뀌면 즉시 걸린다(변이로 확인).

---

## 3. 추가한 가드와 변이 결과

| 가드 | 변이 |
|---|---|
| `test_frontend_accessibility.py` 7 (포커스 표시 대체) | 대체 없이 제거 -> FAIL |
| `test_frontend_accessibility.py` 8 (랜드마크 / 이름 없는 버튼) | `<nav>` 제거 -> FAIL, 이름 없는 버튼 -> FAIL |
| `test_search.py` 화면 전체 계약 | 관심물건이 없는 `thumbnail_url` 렌더 -> FAIL 2건 / 최근본물건 유령 필드 -> FAIL |
| `test_frontend_accessibility.py` 9 (모달 시맨틱, BUGS #149) | role/aria-modal 제거 -> FAIL, 없는 id 를 가리키는 aria-labelledby -> FAIL |

전부 **주입 -> FAIL -> 원복 -> PASS** 확인.

---

## 4. 승인/제품 결정으로 SKIP

- 관심물건·최근 본 물건에 썸네일 추가 (API 필드 + 화면 레이아웃 = 제품 결정)
- 글자 크기·색·간격, 큰글씨 토글
- 마이리스트 내보내기 **구현** — 형식 중립 CSV/TSV 도 지금 만들면 **부르는 곳이 없다**
  (`favorites` 0행, UI 결정 없음). 이 저장소가 `filter/` 에서 이미 겪은 죽은 코드다.
  설계는 `docs/SPRINT219B_MYLIST_EXPORT_FEASIBILITY.md` 에 있다.
- 모바일 실기기 검증 (도구 제약 — 여전히 **확인하지 못함**)
- 모달 **포커스 트랩** — Tab 이 배경으로 빠져나간다. 첫 진입 포커스·순환·복귀를
  직접 관리해야 해서 동작 변경 폭이 크다(별도 작업)
