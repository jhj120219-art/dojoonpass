# Sprint 144 — 물건 사진 / 문서 Asset Pipeline 완성

Status: 완료 (코드·테스트), 일부 SKIP(승인 대기)
Date: 2026-08-17
Scope: 법원 원천 → crawler → 파일시스템 → DB metadata → API → 상세페이지

---

## 0. 한 줄 요약

상세페이지에 **물건 사진이 하나도 없던 이유는 "표시가 안 되던 것"이 아니라 사진을
다루는 계층이 코드·DB·API·화면 어디에도 존재하지 않았기 때문**이고, 문서 쪽은
파일과 상태는 맞는데 **실체 메타데이터(`doc_raw`)가 0행**이라 뷰어가 쪽수조차 알 수
없었다. 두 계층을 실측 기반으로 새로 만들고 이어 붙였다.

---

## 1. STEP 1 — 실측 (코드가 아니라 실제 DB/파일)

측정 시각 2026-08-17, `auction.db` + `documents/`.

| 항목 | 실측값 |
|---|---|
| `auction_item` | 1,876 |
| `document_status` | 5,628 (READY 556 / COLLECTING 5,069 / FAILED 3) |
| `document_queue` | 3,498 (done 559 / pending 2,753 / SKIPPED_EXPIRED 186) |
| **`doc_raw`** | **0행** |
| `parsed_document` | 0행 |
| `documents/` 실제 파일 | 722개 / 1,313.8 MB |
| — 내역 | appraisal.pdf 198, spec.pdf 198, status.html 163, status.json 163 |
| **이미지 관련 컬럼/테이블** | **전 스키마에 0개** |

### 정합성 교차검증 (여기는 깨끗했다)

```
READY인데 파일이 없다        0건
파일이 있는데 READY가 아니다   0건
0바이트 파일                 0건
doc_raw.item_id 고아         0건 (표가 비어 있으므로 자명)
document_status.item_id 고아  0건
```

**즉 이전 스프린트들이 고쳐 온 "거짓 완료" 계열 결함은 실제로 해소된 상태였다.**
이번에 발견한 것은 그 아래층의 다른 문제다.

### 발견한 결함 3건

**(A) `doc_raw` 0행 — 운영 경로에 기록 코드가 아예 없었다** *(계층 D)*

```
doc_raw에 INSERT하는 코드  ->  collect_documents.py:save_doc_raw()   ← 단 한 곳
그 스크립트를 실행하는 것  ->  없음 (스케줄러 3개 어디에도 없다)
실제로 도는 수집 경로      ->  doc_worker.py → collect_document() → mark_queue_done()
                              ← 여기에는 doc_raw 기록이 없었다
```

`test_collect_documents.py`의 첫 줄이 이미 "`doc_raw` 0행이라 저장 경로가 한 번도
검증되지 않았다"고 적어 두고 있었다 — **증상은 기록돼 있었지만 원인(운영 경로가 다른
함수를 탄다)이 짚이지 않아 3개 스프린트를 건너왔다.**

결과: `page_count` / `file_size` / `file_hash` / `doc_version`이 전부 비어 API가
"이 문서 몇 쪽인가"를 답할 수 없었다 → 뷰어의 페이지 이동이 구조적으로 불가능했다.

**(B) 이미지 계층 전면 부재** *(계층 A)*

crawler / 저장경로 / 테이블 / 컬럼 / API / 프런트 — **어디에도 없었다.**
`docs/TEST_PLAN.md` §4가 "이미지: 물건 사진/이미지 기능이 코드에 존재하지 않는다"라고
정확히 적고 있었고 그것이 사실이었다. `docs/auction_detail_wireframe.md`에도 사진
영역이 없다(문서 뷰어만 있다).

**(C) `documents/` 빈 디렉터리 1,674개** *(위생)*

`doc_paths.doc_exists()`가 예전에 조회하면서 `os.makedirs()`를 불렀던 흔적.
원인 코드는 2026-08-14에 이미 고쳐졌고 **쓰레기만 남아 있다**(파일 0개, 손실 없음).

---

## 2. STEP 2 — 법원 원천 실측 (추측 금지)

실제 브라우저로 `courtauction.go.kr` 물건상세(PGJ151F00)를 열어 DOM을 직접 확인했다.
표본 사건: 2024타경3528 / 2022타경101244 / 2023타경110870 / 2020타경111421 /
2023타경2726 / 2023타경106499 / 2025타경311 (서울중앙지방법원).

### 확정된 구조

```
DIV.img_slider
  UL#mf_wfm_mainFrame_gen_pic.list
    LI
      A#mf_wfm_mainFrame_gen_pic_<N>_grp_imgPopup
        IMG#mf_wfm_mainFrame_gen_pic_<N>_img_reltPic
            alt = "<종류>_<순번>"          "전경도_1" / "위치도_4" / "관련사진_5"
            src = "data:image/png;base64,...."
```

### 이 스프린트를 규정한 두 가지 사실

**1. 다운로드할 URL이 없다.** 사진은 별도 파일 URL이 아니라 **페이지 안에 base64
data URI로 박혀서** 온다. 그래서 이 파이프라인에는 "URL 획득 → HTTP 다운로드" 단계가
**존재하지 않는다**. DOM에서 문자열을 읽어 디코드하면 그것이 원본 바이트다.
→ 법원 서버에 **추가 요청 0회**. STEP 2의 질문 ①~⑦ 중 해당하는 것은 ②(HTML에서 직접
추출)뿐이고, ①③④⑤⑥⑦은 전부 아니다.

**2. 선언된 MIME이 틀렸다.** src는 `data:image/png`라고 선언하는데 실제 바이트는
JPEG였다(base64가 `/9j/` = `FF D8 FF`로 시작). 표본 45장 중 JPEG 40장, GIF 5장 —
**단 한 장도 PNG가 아니었는데 전부 image/png로 선언한다.**
→ 확장자를 선언값에서 가져오면 `.png`로 저장된 JPEG가 쌓인다. **항상 매직 바이트로
판정한다**(`sniff_image_ext`).

### 종류 분포 (표본 45장)

| 종류 | 장수 |
|---|---|
| 전경도 | 33 |
| 위치도 | 8 |
| 관련사진 | 2 |
| 내부구조도 | 2 |

`alt`의 순번은 **종류별이 아니라 캐러셀 전체 기준**이다(전경도_1..3 다음이 관련사진_4,5).
그래서 이 숫자 하나로 화면 정렬이 끝난다.

### 다중물건 사건 — 오탐이었던 것을 정정

item 1과 item 2가 **바이트까지 동일한** 사진을 갖는 사건(2025타경311)을 발견해 처음에는
교차오염을 의심했다. **아니었다.** item 2의 상세페이지(물건번호 2, 2층202호)를 직접 열어
해시를 대조한 결과 법원이 실제로 같은 전경도/위치도를 준다(같은 건물이다).
저장된 데이터는 원천에 충실하다.

다만 그 조사 중에 **진짜 위험 하나**를 찾았다 — `go_to_case_detail()`이 `item_no`를
받지 않아 다중물건 사건에서 항상 첫 물건의 페이지로 들어간다. 문서는 버튼 id에
물건번호가 붙어 있어(`..._btn_dspslGdsSpcfc2`) 영향이 없었지만(실측: 파일이 있는
다중물건 사건 22건에서 서로 다른 물건이 같은 바이트인 경우 0건), **사진은 버튼 없이
페이지 DOM을 읽으므로 곧바로 오염이 된다.** 우연에 기대지 않도록 고쳤다.

---

## 3. STEP 3 — 결함 위치 판정

| 계층 | 판정 |
|---|---|
| A. 원천에서 URL/이미지 정보를 못 얻음 | **해당 (사진)** — 얻는 코드가 없었다 |
| B. URL은 얻지만 다운로드 실패 | 해당 없음 (URL 개념 자체가 없다) |
| C. 다운로드는 됐지만 저장 경로 오류 | 해당 없음 |
| D. 파일은 있지만 DB metadata 연결 오류 | **해당 (문서)** — `doc_raw` 0행 |
| E. DB는 정상인데 API가 반환하지 않음 | **해당 (사진·쪽수)** |
| F. API는 정상인데 frontend가 표시하지 않음 | **해당 (사진)** |
| G. 문서는 PDF/이미지 변환 계층이 없음 | 부분 — 썸네일 생성 없음(아래 SKIP) |
| H. 상태값은 COMPLETED/READY인데 실제 asset이 없음 | **해당 없음** (실측 0건 — 이미 해결됨) |

가장 하위 원인부터 고쳤다: A(수집) → D(기록) → E(API) → F(화면).

---

## 4. STEP 4~7 — 구현

### 새 파일

| 파일 | 역할 |
|---|---|
| `crawler/image_assets.py` | 순수 규칙: alt 파싱 / 매직 판정 / data URI 디코드 / 크기 파싱 / 경로 |
| `crawler/image_crawler.py` | selenium 부분: 열린 상세 DOM → 디스크 (원자적 쓰기) |
| `storage/migrations/020_create_auction_image.sql` | `auction_image` 테이블 |
| `api/v1/images.py` | 사진 서빙 (`GET/HEAD /api/v1/item/{id}/images/{seq}`) |
| `backfill_doc_raw.py` | 이미 수집된 556건의 `doc_raw` 백필 (dry-run 기본) |
| `empty_doc_dirs_dryrun.py` | 빈 디렉터리 점검 (삭제하지 않음) |
| `test_asset_pipeline.py` | 이 스프린트 전 계층 회귀 (20개 그룹) |

### 기존 파이프라인 재사용 (새 큐/상태 테이블을 만들지 않았다)

사진은 `document_queue`(`doc_type='image'`)와 `document_status`(`doc_type='IMAGE'`)를
**그대로 쓴다.** 재시도 횟수·우선순위·stale 회수·동시 실행 잠금이 전부 이미 있고
검증돼 있기 때문이다. 새로 만든 표는 `auction_image` 하나뿐이고, 그 이유는 **개수**다:

```
doc_raw          (item, doc_type)당 1행 전제 → 0~N장인 사진을 담을 수 없다
document_status  상태 1행 = 자산 1개 → 사진 5장에 상태 1개라 대응이 무너진다
```

### 저장 경로 (문서와 같은 물건 디렉터리 아래)

```
documents/<법원>/<사건>/<물건>/
    spec.pdf  status.html  status.json  appraisal.pdf
    images/01.jpg  02.jpg  03.jpg  04.gif  05.gif
```

순번은 0으로 채운다(파일명 정렬 = 캐러셀 순서). 확장자는 매직 바이트 판정 결과다.

### 상태 표현 — `NO_IMAGE`를 새로 둔 이유

법원이 사진을 아예 주지 않는 물건이 실재한다. 그때:

- `READY`로 쓰면 화면이 "볼 수 있다"고 **거짓말**한다
- `FAILED`로 쓰면 실패가 아닌 것을 실패로 기록하고 **영원히 재시도**된다

`mark_queue_skipped_expired()`가 같은 이유로 상태를 안 건드리기로 한 것과 같은 고민이며,
여기서는 화면에 표시할 문구가 명확하므로("법원이 사진을 제공하지 않습니다") 상태를 만든다.

### API — 기존 계약을 깨지 않는 순수 추가

`GET /api/v1/item/{id}`에 추가된 키:

```jsonc
"images": [ { "seq", "kind", "url", "thumbnail_url", "width", "height", "file_size" } ],
"image_count": 5,
"representative_image": { ... },      // seq가 가장 앞선 사진, 없으면 null
"images_status": "READY|COLLECTING|NO_IMAGE|FAILED",
"documents": [ {
    "doc_type", "status",             // ← 기존 키 그대로
    "available", "page_count", "file_size", "doc_version",
    "viewer_url", "download_url"      // READY가 아니면 null (열 수 없는 주소를 주지 않는다)
} ]
```

신규 라우트: `GET/HEAD /api/v1/item/{item_id}/images/{seq}` (공개 — 상세 화면이 공개인데
그 화면의 사진만 인증을 요구하면 화면이 깨진다. 문서 뷰어와 같은 판단).

### 프런트 (`src/app/properties/[id]/page.tsx`)

- **물건 사진 카드**: 대표 이미지 / 썸네일 가로 스크롤(`loading="lazy"`) / 라이트박스
  (이전·다음 + ←·→·Esc 키) / 로드 실패한 장을 빈 칸이 아니라 안내로 표시
- **빈 상태를 상태별로 구분**: "사진 수집 중" vs "법원이 사진을 제공하지 않습니다" vs
  "가져오지 못했습니다" — 사용자가 취할 행동이 다르기 때문이다
- **문서 목록 개선**: 수집 전 문서를 더 이상 링크처럼 보이게 하지 않는다(예전에는
  누르면 "문서를 찾을 수 없습니다"만 뜨는 빈 모달이 열렸다), 쪽수 표시, 새 탭 열기
- **문서 뷰어**: 페이지 이동(쪽수를 아는 PDF만), 확대/축소 50~300%, 로딩 표시, 실패 안내

확대/축소는 iframe **요소**를 CSS로 스케일한다(안쪽 문서는 다른 origin이라 내용에 직접
손댈 수 없고, 이 방식은 PDF와 HTML에 똑같이 통한다). 페이지 이동은 PDF 뷰어가 이해하는
`#page=` 프래그먼트를 쓰되 `key`로 재마운트한다.

---

## 5. STEP 8 — 테스트

`test_asset_pipeline.py` 20개 그룹, 전부 통과. selenium 없이 돈다(가짜 드라이버).

주요 불변식:

- 선언 MIME(png)을 무시하고 실제 바이트(jpeg)로 판정한다
- 사진 없음(`no_asset`)은 성공, DOM 규칙 변경은 **실패**(조용한 성공 금지)
- 못 쓰는 데이터(비-data-URI / 이미지 아님 / 너무 작음)는 저장하지 않고 `partial`로 보고
- 같은 순번 중복은 하나만 채택
- 재실행해도 파일이 두 벌 쌓이지 않고, **파일은 있는데 DB만 빈 상태를 스스로 복구**한다
- 법원이 사진을 줄이면 뒤쪽 옛 행이 정리된다
- `mark_queue_done`이 `doc_raw`를 남긴다 / 파일이 없으면 남기지 않는다
- 알 수 없는 `doc_type`은 **여전히 예외로 죽는다**(트랜잭션 롤백 보장)
- 조회만으로 디렉터리가 생기지 않는다(1,674개를 만든 그 사고의 재발 방지)
- `documents/` 밖을 가리키는 `storage_path`는 404
- 프런트/백엔드 필드 계약을 소스 대조로 고정

### 기존 전체 회귀

28개 파일 재실행. 이 스프린트 때문에 **7개 파일이 깨졌고 전부 고쳤다**:

| 파일 | 원인 | 조치 |
|---|---|---|
| `test_doc_storage_atomicity.py` | 모르는 doc_type이 더 이상 예외를 안 냈다 | **코드를 고쳤다**(아래) |
| `test_document_queue.py` | doc_worker 분기 문자열 / 3종류 하드코딩 | 앵커·시드·건수 갱신 |
| `test_pipeline_integrity.py` | doc_type 매핑에 image 추가 | 문서용/전체용 표 분리 |
| `test_api_regression.py` | 새 엔드포인트 미선언 | EXPECTED/PUBLIC/HEAD 목록에 선언 |
| `test_bootstrap.py` | CLAUDE.md 마이그레이션 번호 | 019→020 |
| `test_doc_worker_recovery.py` | 스텁이 `item_no`를 안 받는다 | 스텁 갱신 + 전달 여부 검사 추가 |
| `test_schema_hygiene.py` | 새 migration 파일이 미커밋 | **미해결 — 커밋 필요(아래 SKIP)** |

> **`test_doc_storage_atomicity.py`는 테스트가 옳았다.** 'image'를 넣으면서
> `{...}[doc_type]`을 `.get()`으로 바꿨더니 **오타 난 doc_type이 조용히 성공 처리되어**
> 수집한 적 없는 문서가 done으로 종결되는 상태가 됐다. 고치려던 것보다 나쁜 결함이라
> "레거시 컬럼이 없는 것(image)"과 "아예 모르는 종류"를 나누고 후자는 그대로 죽게 했다.

### 이 스프린트 이전부터 깨져 있던 것 2건 (같이 고쳤다)

- `test_bootstrap.py`: 드리프트가 **해소됐을 때만** 도달하는 줄에서 `sorted()`가
  `None < str`로 죽었다. 상황이 좋아지는 순간 테스트가 죽는 최악의 방향이었다.
- `test_pipeline_integrity.py`: 이름과 주석은 "상한(ceiling)"인데 비교만 `== 1`이라
  지역 오염이 실제로 0이 되자 실패했다. 같은 파일의 다른 상한 검사는 전부 `<=`다.

---

## 6. STEP 2 재검증 — 실제 법원 물건 E2E

프로덕션 수집기(`collect_images`)와 프로덕션 저장(`save_auction_images`)을 실제 법원
페이지에 대고 돌렸다.

```
1차 (임의 표본 6건)   : 성공 6/6, 사진 30/30 저장, 확장자 오판 0건, 7.3 MB
2차 (DB에 있는 9건)   : 상세 진입 9/9, 사진 45/45 저장, auction_image 45행 기록
```

DB→API→브라우저까지 확인: `GET /api/v1/item/502/images/1` → 200 `image/jpeg`
70,100 bytes, 실제 건물 전경 사진이 브라우저에 정상 렌더링됨 (525×700).

**이미지 수집 성공률 100% (45/45), 물건 기준 100% (9/9).**
표본 안에 "법원에 사진이 없는 물건"은 없었다 — `NO_IMAGE` 경로는 합성 테스트로만 검증됐다.

---

## 7. STEP 9 — 성능 실측

### N+1 없음 (확인)

```
item 502 (사진 5장 + 문서 3건)  SQL 7문
item 11855 (사진 5장)           SQL 7문
item 1 (사진 0장)               SQL 7문
```

사진 수·문서 수와 무관하게 **7문 고정**. 이번에 늘어난 것은 2문(`doc_raw`,
`auction_image`)뿐이고 둘 다 인덱스를 탄다:

```
SEARCH auction_image USING INDEX idx_auction_image_item_seq (item_id=?)
```

### 응답/지연

| 항목 | 측정값 |
|---|---|
| 상세 API (사진 5장) | 3.0 ms/req, 3,546 bytes |
| 상세 API (사진 0장) | 3.0 ms/req, 1,395 bytes |
| 사진 서빙 | 3.3 ms/req, 20.4 MB/s |

사진 5장으로 응답이 1.4KB → 3.5KB로 는다. 사진 목록은 **메타데이터만** 담고 바이트는
별도 요청이라, 물건당 사진이 늘어도 상세 응답은 선형으로만 는다.

### 저장 용량

| 항목 | 측정/추정 |
|---|---|
| 사진 (실측 9물건) | 0.69 MB/물건, 5.0장/물건 |
| **사진 전체 추정 (1,876물건)** | **약 1.3 GB** |
| 문서 현재 | 1,294 MB (APPRAISAL 1,213 / SPEC 79 / STATUS 2) |

### 남은 병목 2건 (이번에 고치지 않음 — 근거와 함께 기록)

**(1) 대용량 감정평가서.** 최대 **130.8 MB / 259쪽**짜리 PDF가 실재한다
(`경주지원/2024타경12602`). 평균은 6.2MB/31.6쪽이지만 꼬리가 길다.
현재 뷰어는 이것을 iframe에 통째로 넣는다 → 첫 렌더가 매우 느리다.
그래서 목록·뷰어 양쪽에 **"새 탭" 링크를 함께 뒀다**(받아서 보는 편이 나은 경우가 있다).
근본 해결(쪽 단위 스트리밍/렌더링)은 별도 과제다.

**(2) 사진 중복 저장.** 같은 사건의 여러 물건이 같은 사진을 갖는 경우가 있어
실측 표본에서 **사진 바이트 기준 11.3%(0.70 MB / 6.20 MB)**가 중복이다.
**2026-08-17 정정 — 전체 자산 기준으로는 0.1%다**(중복 0.7 MB / 전체 1,320 MB):
문서가 용량의 99.5%를 차지하고 문서 쪽 중복은 0건이라, 두 숫자를 섞어 읽으면
dedup의 실익을 10배 이상 과대평가하게 된다. `file_hash`를 이미 기록하고
있으므로 해시 기반 dedup(하드링크 또는 공유 저장소)이 가능하다. 전체 corpus 기준
약 150 MB 절감 예상 — 지금 규모에서는 급하지 않다.

### 큐 규모 영향

`enqueue_documents`가 종류를 3→4로 늘렸다. 현재 큐는 3,498행이고 **다음 06:00 크롤에서
물건당 image 행 1개가 추가된다**(최대 +1,876행, 기일 경과분 제외). 큐 자체는
인덱스와 `LIMIT 1` claim이라 행 수 증가에 민감하지 않다.

---

## 7-B. 보안 감사에서 추가로 찾은 것 — 인증 없이 만들 수 있는 500

새 엔드포인트를 프로빙하다 **이 스프린트가 만든 것이 아닌 기존 결함**을 찾았다.

파이썬 int는 무한 정밀도인데 SQLite INTEGER는 64비트다. FastAPI의 `item_id: int`
경로 파라미터는 자릿수를 제한하지 않으므로 큰 수가 그대로 sqlite3에 바인딩되어
`OverflowError: Python int too large to convert to SQLite INTEGER`로 터진다.

```
GET /api/v1/item/999999999999999999999                  -> 500   (기존)
GET /api/v1/item/999999999999999999999/documents/SPEC   -> 500   (기존)
GET /api/v1/item/999999999999999999999/images/1         -> 500   (새 것이 같은 모양을 물려받음)
GET /api/v1/item/502/images/999999999999999999999       -> 500
```

**전부 인증이 필요 없는 공개 경로다.** 데이터가 새거나 서버가 죽지는 않지만,
없는 물건을 물었을 때 404가 아니라 500이 나가고 서버 로그에 스택 트레이스가 쌓인다
(운영 알림을 붙이는 순간 노이즈가 된다).

**[수정]** `api/constants.py`에 `is_sqlite_int()`를 두고 세 엔드포인트가 함께 쓴다.
범위를 벗어난 id는 **404**로 답한다 — 422가 아니다. 형식은 올바른 정수이고 다만
존재할 수 없는 값일 뿐이며, 음수 id가 이미 404인 것과 같은 취급이라 기존 동작과도
일관된다. 정상 트래픽과 경계값(`2**63-1`)은 영향 없음을 확인했다.

**[회귀]** `test_asset_pipeline.py` §18-A — 네 경로 전부 404인지, 경계값이 과잉 차단되지
않는지, 정상 id가 여전히 200인지.

그 밖의 프로빙 결과(전부 정상):

```
seq에 경로 탈출(..%2F..%2Fauction.db)   404
음수 seq / 음수 item_id                 404
non-numeric id                          422 (FastAPI 파라미터 검증)
SQLi 형태 id                            422 (int 파싱 단계에서 차단, 쿼리에 닿지 않는다)
404 응답 본문                           파일시스템 경로/트레이스 누출 없음
DB가 documents/ 밖을 가리키는 경우      404 (realpath + commonpath 검사)
```

---

## 8. 변경 파일

### 신규 (7)
```
crawler/image_assets.py
crawler/image_crawler.py
storage/migrations/020_create_auction_image.sql
api/v1/images.py
backfill_doc_raw.py
empty_doc_dirs_dryrun.py
test_asset_pipeline.py
docs/SPRINT144_ASSET_PIPELINE.md
```

### 수정 (14)
```
storage/database.py          QUEUE_TO_DOC_STATUS_TYPE(+image), LEGACY_HAS_COLUMN,
                             enqueue_documents(+image), mark_queue_done(+status/files_saved,
                             doc_raw 기록), _record_doc_raw, save_auction_images,
                             get_auction_images, to_relative_storage_path, _sha256_file,
                             _pdf_page_count
crawler/doc_crawler.py       collect_document에 image 분기
crawler/base_crawler.py      go_to_case_detail(item_no=None) — 물건번호 우선 매칭
doc_worker.py                image는 버튼 검사 제외, item_no 전달, NO_IMAGE 처리,
                             save_auction_images 호출
config/settings.py           DOC_TYPE_LIST(+image)
api/v1/item.py               images/representative/images_status/page_count/viewer_url 등
api_server.py                images 라우터 등록
src/app/properties/[id]/page.tsx   갤러리·라이트박스·문서 뷰어 개선
test_bootstrap.py            sorted() None 크래시 수정
test_pipeline_integrity.py   ceiling 비교 수정, doc_type 표 분리
test_document_queue.py       앵커/시드/건수
test_api_regression.py       새 엔드포인트 선언
test_doc_worker_recovery.py  스텁 시그니처 + item_no 전달 검사
docs/CLAUDE.md               마이그레이션 019→020
```

### 데이터 변경 (백업 후 수행)
```
auction.db.backup_before_020_20260817_090319   ← 마이그레이션 전 백업
migration 020 적용            auction_image 테이블 생성 (기존 데이터 무손실)
backfill_doc_raw.py --apply   doc_raw 556행 기록 (page_count 확보 394행)
auction_image 45행            E2E 수집분 (서울중앙 9물건)
```

---

## 9. SKIP / 승인 필요 항목

| # | 항목 | 사유 | 정확한 후속 조치 |
|---|---|---|---|
| 1 | **새 파일 커밋** | Commit 금지 지시 | `test_schema_hygiene.py`가 `storage/migrations/020_*.sql` 미추적을 정확히 잡고 있다(검사가 제 일을 하는 중). 커밋하면 즉시 GREEN. 다른 신규 파일 6개도 함께 추적 필요 |
| 2 | **서버 측 썸네일 생성** | Pillow는 설치돼 있으나 **`requirements.txt`에 선언되지 않은 pdfplumber의 전이 의존성**이다. 이것에 기대는 것은 새 의존성 도입과 같고 승인 사항 | `requirements.txt`에 `Pillow==12.3.0` 명시 승인 → `image_assets.py`에 `make_thumbnail()` 추가 → `auction_image`에 `thumb_path` 컬럼(migration 021). API의 `thumbnail_url` 필드는 **이미 만들어 뒀으므로 프런트 계약은 안 바뀐다** |
| 3 | **`documents/` 빈 디렉터리 1,674개 삭제** | `documents/` 하위 파괴적 정리는 승인 영역 | `python empty_doc_dirs_dryrun.py`로 목록 확인 후 그 출력의 PowerShell 한 줄 실행 (worker 미실행 시점에). 파일 0개라 손실 없음 |
| 4 | **고아 디렉터리 `고양지원/2024타경2803/1`** | 실제 파일 4개(12.5MB) 보유 — 삭제 판단 필요 | `cleanup_orphans_dryrun.py`의 [C] 항목. Sprint 이전부터 존재 |
| 5 | **전체 물건 사진 일괄 수집** | 1,876물건 × 브라우저 세션 = 장시간 실 크롤. 운영 배치 실행 판단 | 다음 `doc_worker.py` 정기 실행(02:00)이 큐를 소진하며 자동 수집한다. 즉시 원하면 수동 실행 |
| 6 | **대용량 PDF(130MB/259쪽) 뷰어 최적화** | 설계 변경 규모 | 현재는 "새 탭" 링크로 우회. 쪽 단위 렌더링은 별도 스프린트 |
| 7 | **사진 해시 기반 dedup** | 저장 구조 변경 | **전체 자산의 0.1%(0.7MB/1,320MB)**뿐이라 실익이 거의 없다. 사진만 보면 11.3%지만 용량의 99.5%는 문서이고 문서 중복은 0건이다 — 우선순위 낮음 |

---

## 10. 다음 스프린트 후보

1. **`parsed_document` 0행** — `doc_raw`와 같은 계열의 미사용 표다. 채우는 코드가 어디에도
   없는지, 아니면 실행되지 않는 경로에만 있는지 이번과 같은 방식으로 확인할 것
   (이번 스프린트가 `doc_raw`에서 정확히 그 패턴을 찾았다)
2. **`document_version_log` 0행** — `mark_queue_done`이 `previous_hash != new_hash`일 때만
   쓰는데, 재수집이 한 번도 일어나지 않아 0행일 가능성이 높다. 확인 필요
3. **`config/settings.py:DOC_TYPE_LIST` vs `enqueue_documents`의 하드코딩 튜플** —
   같은 목록이 두 곳에 있고 전자는 아무도 import하지 않는다(Sprint 136이 정리한 것과
   같은 종류의 죽은 중복). 합치는 방향은 `test_schema_hygiene.py`의 소스 대조 방식과
   얽혀 있어 별도 검토 필요
4. **`NO_IMAGE` 실데이터 검증** — 표본에 사진 없는 물건이 없어 합성 테스트로만 검증됐다.
   정기 수집 후 실제 분포를 측정할 것

---

# 부록 — Sprint 144+ 전수 검증 (2026-08-17, 같은 날 이어서)

Sprint 144 직후 **실제 production `doc_worker.main()`을 그대로 돌려** 전 계층을 검증하고,
그 과정에서 새 결함 1건(BUGS #100)을 찾아 고쳤다.

## A. 실제 worker 실행 검증 (임시 DB, 운영 auction.db 무손상)

수집 경로를 흉내내지 않고 **`doc_worker.main()`을 그대로 호출**했다. claim ->
`go_to_case_detail(item_no 포함)` -> `collect_document()` -> `mark_queue_done()` ->
`save_auction_images()` 전 구간이 운영 코드다.

| 대상 | 결과 |
|---|---|
| `image` / 2024타경3528-1 | exit 0, queue=done, `document_status.IMAGE=READY`, `auction_image` 5행, 파일 5개, 24.5초 |
| `status` / **2025타경311-2** | exit 0, queue=done, `STATUS=READY`, `doc_raw` 1행(12,014B), 파일 2개, 21.8초 |

두 번째가 이번 스프린트의 핵심 증명이다 — **물건번호 2의 현황조사서는 이전까지 구조적으로
수집이 불가능했다**(BUGS #100). 실행 후 `logs/doc_worker.lock`이 정상 해제됐고 운영
`auction.db`/`documents/`는 건드리지 않았음을 확인했다.

## B. 전수 무결성 (표본이 아니라 전 건)

```
파일 767개 전부 열어봄   손상 PDF 0 / JSON 0 / HTML 0 / 이미지 0
                        0바이트 0 / 512B 미만 0 / 잔여 .tmp 0
DB<->파일 전수 대조      doc_raw 556행, auction_image 45행 -> path/size/SHA-256 불일치 0
API 전수 스윕           READY 556 -> {200:556} / 이미지 45 -> {200:45}
                        비-READY 400 -> {404:400}  (잘못된 200 노출 0)
고아 파일                4개 (고양지원/2024타경2803 — Sprint 이전부터 존재)
```

## C. 성능 (STEP 10)

```
상세 API      2.6~3.3 ms (p95 3.8 ms) — 자산 수와 무관, SQL 7문 고정
사진 서빙     3.2 ms
appraisal 2.4MB   9.7 ms
★ 최대 131MB PDF  399 ms        <- 실질 병목 (뷰어에 "새 탭"을 둔 이유)
documents/ 전체 walk 138 ms     <- 요청당 하면 안 되는 비용. API는 하지 않는다(확인)
PDF page_count 49 ms(131MB)     <- doc_raw 캐시가 필요한 이유
이미지 크기 파싱 0.001 ms        <- Pillow 없이 stdlib, 무시 가능
```

### 규모 위험 (측정만 — 최적화하지 않음)

```
측정치   사진 0.69 MB/물건(5.0장) · 문서 6.47 MB/물건
현 corpus 완주   13.1 GB   |  1만 물건  69.9 GB  |  10만 물건  699.2 GB
로컬 여유        832.8 GB / 930.6 GB
```

**진짜 위험은 디스크가 아니라 OneDrive다** — `documents/`가 동기화 폴더 안이라 13 GB가
개인 OneDrive로 올라간다. 기존에 문서화된 OneDrive 이슈(빌드 EPERM / BUGS #35)와
**같은 원인의 다른 축**이라 새 항목을 만들지 않고
`docs/BETA_RELEASE_CHECKLIST.md`의 해당 항목을 보강했다.

## D. 정정 — 중복 바이트 11.3%

본문 §7의 "중복 11.3%"는 **사진만** 놓고 본 값이다. 전수 측정 결과 **전체 자산 기준으로는
0.1%**(0.7 MB / 1,320 MB)다 — 용량의 99.5%가 문서이고 문서 중복은 0건이다.
dedup의 실익은 본문이 시사한 것보다 훨씬 작다.

## E. 추가 기술부채 (이번에 손대지 않음)

`logs/` 안에 2026-08-03자 **운영 스크립트 사본 3개**가 있다
(`doc_worker.py` / `mvp_scraper.py` / `refresh_priority.py`). 이미 존재하지 않는 함수를
import하므로(`crawl_single_document` — 전 저장소에 0건) 실행하면 즉시 ImportError다.
`logs/`는 gitignore 대상이라 추적되지 않으며, **파일 삭제는 승인 영역**이라 그대로 뒀다.
디버깅 중 이 사본을 실제 코드로 오인할 위험이 있어 기록만 남긴다.
