# Sprint 163 — DB / Storage 감사: 결함 없음 (전부 실측)

작성 2026-08-17. 모든 수치는 실행 결과다. **코드를 바꾸지 않았다** — 고칠 것이 없었다.

---

## 1. 무결성

```
PRAGMA integrity_check     ok
PRAGMA foreign_key_check   위반 0건
PRAGMA foreign_keys        1 (켜져 있다)
DB 파일 크기               5.0 MB
명시 인덱스                63개
```

## 2. 고아 행 — 0건

`item_id` 로 `auction_item` 을 참조하는 테이블 전부를 확인했다.

```
document_status  고아 0        doc_raw       고아 0
auction_image    고아 0        favorites     고아 0
recent_items     고아 0
document_queue   — item_id 컬럼이 없다(court_code+case_no+item_no 로 식별). 아래 4절 참조
```

## 3. DB ↔ 디스크 일치 — 완전 일치

등록된 모든 파일을 **실제로 열어** 확인했다(존재·크기).

```
doc_raw        556행   경로없음 0 / 파일없음 0 / 0바이트 0 / 크기불일치 0
auction_image   45행   경로없음 0 / 파일없음 0 / 0바이트 0 / 크기불일치 0
```

`file_size` 컬럼과 디스크 실제 크기가 **556 + 45건 전부 일치**한다.

### 역방향 — 디스크에만 있는 파일 166개는 대부분 설계다

```
디스크 문서 파일 722개 / doc_raw 등록 556개 -> 차이 166개

파일명 분포
   status.html    163      <- doc_raw 는 status.json 을 대표 파일로 기록한다
   status.json      1
   appraisal.pdf    1
   spec.pdf         1
```

`crawler/doc_paths._PRIMARY_EXT` 가 STATUS 의 "수집 완료 판정 기준 파일"을 **json** 으로
정하고, 뷰어는 html 을 서빙한다. 즉 `status.html` 이 `doc_raw` 에 없는 것은 **정상이다.**

확인: `status.html` 163개 중 **162개**는 같은 폴더의 `status.json` 이 `doc_raw` 에 있다.
짝이 없는 것은 1개뿐이고, 그것이 아래 4절의 알려진 고아다.

## 4. 유일한 이상값은 **이미 알려져 있고 변하지 않았다**

`documents/고양지원/2024타경2803/1/` 에 파일 4개(12.4 MB)가 있는데 `doc_raw` 에 없다.
추적해 보니 법원 귀속이 갈린 사례였다.

```
디스크/큐(7월)   고양지원 2024타경2803  queue 301~303 = done
auction_item     id=540  춘천지방법원 2024타경2803  (고양지원 행은 없다)
document_status  item 540 -> SPEC/STATUS/APPRAISAL 전부 COLLECTING
doc_raw          item 540 -> 0행
queue(8월)       13741~13743  춘천지방법원  pending
```

**새 발견이 아니다.** `cleanup_orphans_dryrun.py` 의 머리말이 2026-08-14에 이 사건을
이름까지 적어 두었다. 오늘 그 스크립트를 다시 돌려 **수치가 그대로인지** 확인했다.

```
빈 고아 디렉터리          4  (고양지원 2024타경8092 / 부산동부지원 2023타경5187 /
                             성남지원 2024타경4973 / 포항지원 2024타경4705)
파일이 든 고아 디렉터리    1  (고양지원 2024타경2803, 12,471.1 KB)
고아 큐 행               18
```

08-14 문서의 수치와 **동일하다 — 3일간 늘지 않았다.**

삭제는 그 스크립트 자신이 "되돌릴 수 없는 운영 데이터 파괴"라고 못박고 있고
`/goal` 의 SKIP 항목이기도 하므로 **하지 않았다.** 특히 [C](파일이 든 고아)는
"물건 행이 왜 사라졌는지가 먼저"이며 유일한 사본일 수 있다.

## 5. 성능 — 병목 없음 (그래서 인덱스를 추가하지 않았다)

가장 큰 테이블(`document_status` 5,628행)이 인덱스 1개뿐이라 실행 계획을 봤더니
`status` 기준 조회는 **SCAN** 이었다. 그러나 고치기 전에 **재 봤다.**

```
document_status (5,628행)
  status 집계(GROUP BY)      p50 0.691ms   p95 0.794ms   max 1.598ms
  READY 목록                 p50 0.612ms   p95 0.724ms
  item_id+doc_type 단건      p50 0.023ms   p95 0.025ms   (인덱스 사용)
  doc_raw 조인               p50 0.584ms   p95 0.699ms
document_queue 집계          p50 0.144ms
auction_item 기본 검색       p50 0.053ms
```

**전부 1ms 미만이다.** 5천 행 규모에서 SCAN 은 비용이 아니다. 인덱스를 더 만들면
읽기 이득은 측정 불가 수준인데 쓰기 비용과 DB 크기만 는다.

> `/goal` 규칙 그대로다 — *"실제 병목이 확인된 경우에만 개선한다. 숫자 없이 성능
> 개선을 주장하지 않는다."* 숫자를 봤고, 병목이 아니어서 **아무것도 하지 않았다.**
> 데이터가 수십만 행으로 늘면 다시 재야 한다는 점만 남긴다(지금 추정하지 않는다).

## 6. 이번 감사에서 바꾼 것

```
없음. 측정만 했다.
```

## 7. 남은 것 (승인 영역)

- 고아 디렉터리 5개 / 고아 큐 18행 정리 — 운영 판단(파괴적). `cleanup_orphans_dryrun.py`
  가 판단 근거를 이미 만들어 두었다.
- `document_queue` 에 `item_id` 가 없어 다른 테이블과 조인 규칙이 다르다
  (court_code + case_no + item_no 3자 매칭). 스키마 변경은 승인 영역이라 기록만 한다.
