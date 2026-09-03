# Sprint 287 — 성능/구조 감사: 초기 번들의 24%가 **쓰지도 않는 시점에** 실려 있었다 (2026-09-03)

> **실행 환경**: 데스크탑3(개발/QA). `auction.db` 는 migration 020 까지만 적용된 개발
> 데이터(물건 1,876 / 사건 1,384 / 최신 crawl_date 2026-08-12)다.
> **운영 판정으로 읽지 않는다**(BUGS #200, `docs/machine-roles`).
>
> **DB 스키마·migration·운영 데이터를 건드리지 않았다.** 변경은 프런트 소스 11개와
> 새 검사 파일 1개뿐이다(+86 / -36 줄).

---

## 요약

| # | 무엇 | 종류 | 사용자 영향 |
|---|---|---|---|
| 1 | 공용 헤더가 supabase-js 전체를 **모든 라우트의 초기 번들**에 실었다 | ★ 결함(수정) | 첫 화면 JS 265.5 -> 205.6KB gzip (-22.6%) |
| 2 | 그 청크가 정적/동적 라우트용으로 **두 벌** 빌드되고 있었다 | 결함(부수 해소) | 정적 청크 총량 375.5 -> 326.8KB gzip (-13%) |
| 3 | 클라이언트 번들 경계 검사 신설(import 그래프 + 빌드 예산) | 가드 | 같은 회귀가 조용히 돌아오지 못한다 |
| 4 | 목록 썸네일이 **원본 해상도**를 그대로 내려준다 | 측정(승인 대기) | 지금 0.5% 커버리지라 무해. 100%면 페이지당 ~2.8MB |
| 5 | SQLite / API 는 현재 규모에서 병목이 아니다 | 재측정 | 없음(기존 Sprint 134/255 결론 재확인) |
| 6 | P1 백로그 8~13 은 **이미 구현되어 있다** | 재확인 | 없음(실화면·실데이터로 확인) |

---

## 1. ★ 결함 — 공용 헤더 하나가 초기 번들의 24%를 만들었다

### 무엇을 쟀나

production build(`npm run build`, Next 16.2.9 / Turbopack) 산출물에서, 사전 렌더된
HTML 이 실제로 부르는 `<script>` 를 전부 모아 **디스크의 그 파일들을 gzip 해서** 더했다.
개발 서버 느낌이 아니라 배포되는 바이트다.

```
청크                        raw        gzip     쓰는 라우트
-------------------------  ---------  -------  ----------------------------------
2nykiepra7i1k.js            222.2K     69.4K   전부 (react-dom)
2u-ekoys4vh_m.js            242.9K     64.3K   전부  <- ★ supabase-js + SiteHeader
00_jg3qe47nl9.js            242.9K     64.3K   전부(동적 라우트용 **사본**)
2iusi4sviyzf0.js            190.1K     48.0K   전부 (Next 클라이언트 런타임)
0cz1d0mv5g_q7.js            110.0K     38.5K   전부 — **noModule**(최신 브라우저는 안 받음)
```

청크 내용은 문자열로 확인했다 — `2u-...` 안에 `GoTrueClient` / `RealtimeClient` /
`createBrowserClient` 와 헤더의 `콕찰` 이 함께 들어 있다. 즉 **헤더 컴포넌트와
supabase-js 가 한 청크**다.

### 왜 그렇게 됐나

`src/components/SiteHeader.tsx` 는 8개 화면 전부가 쓰는 유일한 공용 헤더인데,
로그인 이메일 한 줄을 그리려고 `@/lib/supabaseClient` 를 **정적 import** 했다.
그 파일이 `@supabase/ssr` 을 정적 import 하고, `@supabase/ssr` 은 `supabase-js`
전체(auth + postgrest + realtime + storage + functions)를 끌어온다. realtime 은
`SupabaseClient` 생성자에서 무조건 만들어지므로 트리셰이킹으로 빠지지 않는다.

결과적으로 **로그인하지 않은 첫 방문자도, 404 화면도** 이 243KB 를 받았다.

### 그런데 아무도 렌더 중에 쓰지 않는다

`createClient()` 호출 지점 12곳을 전수로 봤다. **전부** `useEffect` 안이거나
클릭 핸들러 안이다 — 렌더 경로에 한 곳도 없다.

```
SiteHeader              useEffect
FavoriteButton          onClick
SearchPresets           useEffect
favorites/page          useEffect      mypage/page          useEffect
properties/recent       useEffect      favorites/import     핸들러
properties/[id]         useEffect 1 + 핸들러 2
FavoriteNote            핸들러          LogoutButton         핸들러
```

즉 hydration 을 막을 이유가 없었다. 초기 번들에 있을 이유도 없었다.

### 고친 방식 — 정본 한 곳에서만 늦춘다

`src/lib/supabaseClient.ts` 가 `import('@supabase/ssr')` 로 바꾸고, 만들어진
클라이언트를 모듈 수준 Promise 로 캐시한다. 호출부 12곳은 `await` 한 줄이 붙을 뿐이다
(전부 이미 async 함수 안이라 형태가 바뀌지 않는다).

**동작은 바뀌지 않는다.** `createBrowserClient` 는 브라우저에서 이미 싱글턴이라
(`node_modules/@supabase/ssr` 의 `cachedBrowserClient`) 매번 부르든 캐시하든 같은
인스턴스다. 달라지는 것은 반환값이 Promise 라는 점 하나다.

`SiteHeader` 의 effect 만 모양을 바꿨다 — effect 자체는 async 가 될 수 없으므로
`createClient().then(...)` 안으로 옮기고, 구독 해제를 `unsubscribe` 변수로 넘긴다.
**실패했을 때의 화면은 그대로 뒀다** — 세션 확인이 실패하면 예전에도 `authChecked` 가
false 로 남아 로그인/로그아웃 어느 쪽도 그리지 않았다. 여기서 '로그인' 을 띄우면
로그인한 사용자에게 로그아웃된 것처럼 보이게 만드는 **새 동작**이 된다.

### BEFORE -> AFTER (production build, gzip, noModule 폴리필 포함)

```
라우트                 BEFORE     AFTER      차이
-------------------  ---------  ---------  --------
/                     265.5K     205.6K     -59.9K   (-22.6%)
/search               265.5K     205.6K     -59.9K   (-22.6%)
/favorites            258.2K     200.4K     -57.8K
/favorites/import     258.1K     200.3K     -57.7K
/mypage               257.0K     199.3K     -57.8K
/properties/recent    256.5K     198.7K     -57.8K
/login                255.4K     195.7K     -59.8K
/_not-found           251.1K     191.3K     -59.8K

정적 청크 총량         375.5K     326.8K     -48.7K   (-13%, 사본 하나가 사라졌다)
```

빌드가 supabase 청크를 정적/동적 라우트용으로 **두 벌** 만들고 있었는데(둘 다 64.3K),
동적 import 로 바뀌면서 한 벌로 합쳐졌다. 바이트 동일 중복 청크는 이제 0개다.

### 실제 브라우저로 확인했다 (로그인 상태, `/search`, `/properties/505`)

```
초기 청크 10개  ... 632ms 에 완료
supabase 청크   ... 675ms 에 완료   <- hydration 뒤에 따라온다
헤더 렌더        "콕찰 | ... | jab31@naver.com | 로그아웃"   (인증 정상)
```

**정직한 트레이드오프**: 상세 화면(`/properties/[id]`)은 물건 조회가 토큰을 먼저
얻어야 하므로, 그 fetch 가 청크 도착만큼(실측 로컬 +43ms) 뒤로 밀린다. 총 바이트는
같고 순서만 바뀐다 — 고치기 전에는 **그 63KB 가 도착해야 hydration 이 시작**됐다.
첫 페인트/상호작용 가능 시점은 앞당겨지고, 데이터 도착은 실질적으로 같다.

---

## 2. 남은 초기 번들은 프레임워크 바닥이다 (CURRENT NORMAL)

고친 뒤 `/search` 초기 JS 205.6KB gzip 중 137KB 가 react-dom + Next 런타임이고,
38.5KB 는 `noModule` 폴리필이라 **최신 브라우저는 받지 않는다**(HTML 의 `noModule`
속성으로 확인, Chrome 네트워크에서 실제로 요청되지 않는 것도 확인).
최신 브라우저 기준 실 초기 JS 는 **167.1KB gzip** 이다.

애플리케이션 코드가 공용 청크를 부풀리는 자리는 이제 **없다**. 라우트별 자기 청크는
4.4~12.7KB gzip 이다(검색 폼이 가장 크다: 12.7K).

---

## 3. 가드 — `tests/client-bundle-boundary.test.mjs` (신규 6검사)

같은 회귀가 돌아오면 **화면은 똑같이 잘 보이고 느려지기만 한다.** 사람이 눈으로
발견하기 어려운 종류라 검사로 잠근다. 두 층으로 본다.

**(a) 소스 — import 그래프**. "SiteHeader 가 supabase 를 import 하지 않는다" 만 보면
한 칸만 우회해도 통과한다(헤더 -> 새 헬퍼 -> supabase). 그래서 `'use client'` 진입점
전부에서 **정적 import 만** 따라가 닫힘을 만들고, 그 안에 지정 패키지가 있으면 실패한다.

세 가지는 일부러 뺀다 — 넣으면 검사가 **없는 무게를 있다고** 말한다.
- 동적 `import(...)` : 별도 청크다(이 파일이 지키려는 바로 그 방식)
- `import type ...` : 컴파일에서 지워진다(런타임 0바이트)
- `'use server'` 모듈 : 클라이언트에는 참조 스텁만 들어간다

**뒤 둘은 실제로 오탐을 냈다** — 첫 판이 `login/page.tsx -> actions.ts ->
supabaseServer` 와 `supabaseClient.ts 의 import type` 을 위반으로 잡았다. 고쳤다.

**(b) 빌드 산출물 — 초기 JS 예산 185KB gzip**(noModule 제외). supabase 뿐 아니라
**어떤 무거운 것이 들어와도** 잡는다. 빌드가 없으면 통과가 아니라 skip 이다.

### Mutation — 두 층 모두 실제로 붉어진다

```
A. `supabaseClient.ts` 를 정적 import 로 되돌림
   (a) 소스 검사        **검출** (경로까지 출력: SiteHeader -> supabaseClient -> @supabase/*)
   (b) 예산 검사(빌드 후) **검출** favorites 162.1 -> 220.1KB > 185
   나머지 4검사          통과 유지(오탐 없음)

B. 되돌린 상태로 tsc/eslint/build
   전부 초록 -> 기존 게이트는 이 회귀를 **하나도 잡지 못한다**. 그래서 이 검사가 필요하다.

C. 복구 후 재빌드
   6/6 통과
```

예산값 근거: 현재 최댓값 162.1KB + 여유 23KB. 되돌아간 상태(220.1KB)를 35KB 차이로
넘긴다 — 아슬아슬한 값이 아니다.

---

## 4. 승인 필요 — 목록 썸네일이 원본 해상도를 그대로 내려준다

**측정만 했고 고치지 않았다.** 고치려면 새 의존성이 필요하다.

```
실측(실제 브라우저, cache:'reload' 로 5장을 다시 받음)
  전송량 합계          704KB  (장당 평균 141KB, 최대 236KB)
  렌더 크기            78 x 78 CSS px
  원본 크기            522 x 700 (자연 해상도)
  과표집               60배 (DPR 2 기준으로도 15배)
  20장 카드 페이지 환산  ~2.8MB

현재 노출도
  auction_image 보유 물건  9 / 1,876 = 0.5%
  -> **지금은 실제 문제가 아니다.** 대부분의 검색 페이지는 이미지 0바이트다.
```

즉 이것은 **A(현재 문제)가 아니라 B(미래 드리프트)** 다. 사진 수집이 진행돼 커버리지가
올라가는 만큼 정확히 비례해 나빠진다. 참고로 고친 뒤 초기 JS 는 162KB 이므로,
커버리지 100% 시 이미지가 JS 예산의 **17배**를 차지한다.

이미 되어 있는 완화(확인함): `loading="lazy"`, 조건부 요청(304), 대표 1장만 배치
조회(N+1 없음), 없는 물건은 자리 자체를 만들지 않음.

### [APPROVAL REQUIRED] 제안

```
무엇        서빙 시점 축소본 1종(예: 긴 변 160px, JPEG q75)을 만들어
            목록에서는 그것을 준다. 상세의 큰 사진은 원본 유지.
왜 승인     Pillow 가 필요하다. 이 환경에 설치되어 있지만
            **requirements.txt 에 선언되어 있지 않고 저장소 코드가 한 번도 쓰지 않는다**
            (`grep -rn "from PIL" --include=*.py` 0건).
            새 의존성 선언 = 승인 영역.
영향        `api/v1/images.py` 서빙 경로 + 파생 파일 캐시 위치 결정
            (documents/ 안인지 별도인지 = 저장소 레이아웃 결정)
예상 효과   장당 141KB -> 약 8~15KB. 20장 페이지 2.8MB -> 0.2~0.3MB
migration   불필요 (auction_image 스키마 그대로. width/height 는 이미 있다)
대안        축소를 하지 않는다면 목록에서 사진을 빼는 것도 선택지다 — 그건 제품 결정이다.
```

---

## 5. SQLite / API — 현재 규모에서 병목이 아니다 (재측정)

Sprint 134 / 255 의 결론을 이번 빌드/이번 DB 로 다시 쟀고, **같은 답**이 나왔다.
새 결함 없음.

```
쿼리 (EXPLAIN QUERY PLAN + 30회 중앙값, 1,876행)
  기본 목록 20건       0.108ms  SCAN idx_auction_item_default_sort + TEMP B-TREE(마지막 항)
  기본 COUNT           0.041ms  COVERING INDEX
  기일 >= 오늘         0.032ms  SEARCH idx_auction_item_default_sort
  sido + sigungu       0.085ms  SEARCH idx_ai_sido
  주소 LIKE '%x%'      0.294ms  SCAN  (인덱스 불가 — 구조상)
  주소 LIKE COUNT      0.410ms  SCAN  (전체 스캔)
  최저가 정렬          0.091ms  SEARCH idx_auction_item_minimum_bid_price
  OFFSET 1800(90쪽)    1.300ms  SCAN  (OFFSET 에 비례)
  regions DISTINCT     0.053ms  COVERING INDEX

HTTP (15회 중앙값)
  /search size=20      7.03ms   11.8KB
  /search size=100    10.19ms   58.0KB
  /search page=90      8.23ms   11.4KB
  /search regions      4.67ms    0.3KB
  /item/505            5.51ms    3.5KB   (쿼리 8개, 전부 item_id 키. 루프 없음 = N+1 아님)

프런트 중복 호출
  /search      API 1회 (search-presets). 검색 자체는 서버 렌더.
  /properties/[id]  4회, 중복 0.  /mypage  3회를 Promise.all 로 병렬.
```

**FUTURE DRIFT** (결함 아님, 기록): `full_address LIKE '%x%'` 와 `status LIKE` 는
인덱스를 쓸 수 없고 `COUNT(*)` 가 매 요청 전체 스캔이다. OFFSET 페이지네이션도
깊은 페이지에서 선형이다. 지금은 전부 1ms 미만이라 **고칠 근거가 없다** — 규모가
자릿수로 커질 때 다시 잰다.

### 중복 인덱스 4개는 결함이 아니라 **이 머신의 DB 나이**다

`auction_item(auction_date)` / `(case_no)` / `(minimum_bid_price)` /
`rights_summary(item_id)` 가 두 벌씩 있는데, 이것을 지우는 migration
`021_drop_duplicate_indexes.sql` 이 **이미 저장소에 있다**. 이 머신의 DB 가 020 에
멈춰 있어서 보이는 것이다(`test_schema_hygiene` 가 정확히 그것으로 붉다).
**migration 을 실행하지 않았다**(승인 영역).

---

## 6. P1 백로그 8~13 — 문서를 믿지 않고 실화면으로 다시 확인했다

`/properties/505` 를 실제 브라우저로 열어 렌더된 텍스트를 읽었다.

```
8  이미지 갤러리      "물건 사진 5장" + 대표 + 썸네일 줄 + 라이트박스   DONE
9  문서수집상태 배지   매각물건명세서2쪽/현황조사서/감정평가서19쪽 각 "수집완료"  DONE
10 권리분석 신뢰도/충돌 "신뢰도 HIGH / 정보원 STATUS ✓ 확보 SPEC ✓ 확보
                       / 충돌: 충돌 없음 / 경고: 경고 없음"          DONE
11 case 정보         "사건 정보 / 사건종류 · 접수일 · 배당요구종기일"  DONE(아래 주의)
12 crawl_date        "최근 수집일 2026-08-12"                        DONE
13 Number/Money      "367,000,000원" · "3.8억" · "80.0%"             DONE
```

**11 의 값이 전부 `-` 인 것은 결함이 아니다.** 이 머신의 `auction_case` 는
`case_type`/`filed_date`/`demand_deadline` 이 1,384건 **전부 NULL** 인데, 그 생산자는
Sprint 285 가 복구해 이 작업트리에 들어 있다(`normalizer.py:372`,
`migrate_execute.py:87~243`). 020 시점 DB 에 그 컬럼이 채워져 있을 리가 없다.
운영 머신에서 크롤이 한 번 돌면 채워진다 — 여기서 판정할 수 없는 항목이다.

14(접근성)은 `test_frontend_accessibility.py` 통과(단언 87) + node 접근성 검사 통과로
현 상태 유지를 확인했다. 새로 고칠 거리를 찾지 못했다.

---

## 7. 찾았지만 **고치지 않은** 것들 (근거 포함)

```
/properties/[id] 가 1,490줄짜리 통짜 클라이언트 컴포넌트다
  -> 자기 청크는 9.4KB gzip 로 작다. 서버 컴포넌트 + 클라이언트 섬으로 쪼개면
     첫 페인트에 본문이 실릴 수 있지만, 즐겨찾기/등기부/문서뷰어/라이트박스/
     이전-다음 이동 상태가 전부 얽힌 대수술이다. **번들 이득은 사실상 0** 이고
     회귀 위험만 크다. 야간 자율 실행에서 손댈 종류가 아니다. 기록만 남긴다.

src 안의 "다른 파일이 안 쓰는 export" 51개
  -> 전수 확인 결과 Next 규약(page/layout/metadata/proxy/config), tests/ 가 쓰는 것,
     자기 파일 안에서 쓰는 것뿐이다. **죽은 코드 0건.** `export` 키워드만 불필요한
     4개(PRICE_OPTIONS 등)는 번들 영향이 없어 그대로 둔다.

favorites.deleted_at / idx_favorites_deleted_at
  -> API 는 하드 DELETE 만 쓴다(읽는 쪽도 쓰는 쪽도 0곳). 소프트 삭제 잔재다.
     **버그는 아니다**(검색의 찜 조회가 `deleted_at IS NULL` 을 빠뜨린 것이 아니라,
     애초에 소프트 삭제를 하지 않는다). 제거는 스키마 변경 = 승인 영역.

목록 썸네일에 decoding="async" 추가
  -> 효과를 이 환경에서 신뢰성 있게 잴 수 없다. 재지 못한 최적화는 넣지 않는다.
     위 4번 승인 항목에 함께 적어 둔다.
```

---

## 8. 게이트

```
tsc          0
eslint       0
npm run build 성공 (Turbopack, 11 페이지)
node         326건 / 322 pass / 0 fail / 4 skip   (320 -> 326, 신규 6검사)
python       통과 64 | 실패 4 | 건너뜀 3 | 판정없음 1 | 시간초과 0
             단언 11,888 / 197.2s
             실패 4 = test_auction_identity / test_bootstrap /
                      test_pipeline_integrity / test_schema_hygiene
             -> 전부 **이 머신 DB 가 021~029 미적용**이라서다. 원인을 확인했고
                코드 결함이 아니다. migration 은 실행하지 않았다(승인 영역).
제품 코드     프런트 11파일 (+86 / -36). DB·스키마·migration·.env·운영데이터 무변경.
```

### 판정 한계 (정직하게)

- **비로그인 상태의 헤더 렌더를 브라우저로 직접 보지 못했다.** 이 브라우저 세션이
  로그인 상태이고, 로그아웃시키는 것은 사용자 브라우저 상태를 바꾸는 일이라
  하지 않았다. 로그인/비로그인 분기는 같은 `.then` 안의 두 갈래이고 실패 동작을
  일부러 보존했으며, 로그인 화면(비로그인 대상)과 node 계약 검사 108건은 통과한다.
- **콜드 로드 LCP 의 before/after 비교는 하지 못했다.** 고치기 전 빌드를 이미 덮어썼고
  로컬 루프백은 네트워크 지연이 없어 의미 있는 차이를 만들지 못한다. 대신 배포되는
  **바이트**와 **청크 도착 순서**를 실측했다.
