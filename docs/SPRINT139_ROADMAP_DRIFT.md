# Sprint 139 ― `docs/roadmap.md`의 5개 오래된 항목 정정 (2026-08-16)

> 앞 Sprint: `docs/SPRINT138_TEST_GAP_AND_COURT_CRAWLER_RESTART.md`
>
> **별도 파일 이유**: Sprint 100~138과 같다.

Documentation Drift Audit — 이 세션이 아직 대조하지 않았던 `docs/roadmap.md`
(`Last Updated: 2026-08-07`, Sprint 28 시점)를 코드/실측과 대조했다. 상당 부분은
"[완료]"로 이미 표시된 과거 Sprint 로그라 손대지 않았고, **현재 상태를 주장하는**
"In Progress"/"Next Priority"/"Technical Debt" 세 섹션만 집중 확인했다.

## 발견 및 정정 (5건)

1. **`ADMIN_API_KEY`/`SUPER_ADMIN_API_KEY` 미설정** (3곳에서 반복 언급) ―
   Sprint 135/138이 이미 정정한 것과 같은 사실이 `roadmap.md`에는 아직 남아
   있었다. 이번엔 `.env` grep보다 한 단계 더 강한 증거로 정정했다 — Sprint 138의
   라이브 서버 기동 중 확보한 실측: 키 없이 Admin 엔드포인트를 호출하면
   `500 관리자 키 미설정`이 아니라 `403 권한이 없습니다`가 온다(코드 계약상
   값이 실제로 채워져 있어야만 나오는 응답).
2. **"selenium 미설치"** ― `python -c "import selenium"`이 성공한다(Sprint 137에서
   이미 이 세션 자체가 selenium을 써서 doc_worker 테스트를 작성했다 — 그때
   알게 된 사실을 이번에 roadmap.md에도 반영). `test_docs.py` 등이 기본
   실행되지 않는 진짜 이유는 의존성 부재가 아니라 `ALLOW_LIVE_CRAWL=1` 가드
   (의도된 설계)임을 명확히 구분해 적었다.
3. **"`storage/`가 통째로 gitignore"** ― `docs/CLAUDE.md`가 이미 2026-08-13에
   정정해 둔 사실(Sprint 51에 규칙 정밀화, 소스 23개 정상 추적)이 `roadmap.md`에는
   반영되지 않고 있었다. 다른 문서는 맞는데 이 문서만 옛 상태였던 경우 —
   대조 없이는 못 잡는 종류.
4. **"Admin 인증에 역할 구분 없음"** ― 부분적으로만 사실이다. 2단계
   (ADMIN/SUPER_ADMIN) 역할 구분 자체는 이미 도입돼 있고(이 세션이 오늘
   API Contract Audit에서 직접 재확인함 — 돈/권한 이동 4개 엔드포인트가
   SUPER_ADMIN 전용), 남은 것은 "등급 안에서 개별 운영자 식별"뿐이다. 전체를
   틀렸다고 지우지 않고 정확히 남은 부분만 남겼다.
5. **`(user_id, status)` 복합 인덱스 부재 → TEMP B-TREE** ― 사실 관계는 지금도
   정확하다(재실측으로 확인: `SEARCH ... USING INDEX idx_subscriptions_user_id`
   다음 `USE TEMP B-TREE FOR ORDER BY`가 그대로 뜬다). 하지만 **평가가 빠져
   있었다** — 이 TEMP B-TREE는 `WHERE user_id=?`로 이미 한 사용자로 좁혀진
   행만 정렬한다(한 사용자의 평생 구독 이력은 실질적으로 한 자릿수).
   Sprint 134가 찾은 search 정렬의 TEMP B-TREE(테이블 전체 대상)와 겉모습은
   같지만, 이쪽은 **전체 데이터가 아무리 늘어도 사용자당 비용은 늘지 않는다**
   — 위험 등급이 다르다는 것을 실측으로 못박아 다음 세션이 두 가지를
   혼동하지 않게 했다.

## 왜 이게 문제인가

다섯 항목 모두 "아직 해야 할 일"로 보이는 자리에 있었다 — 특히 1번은
`docs/roadmap.md`의 "Next Priority"/"Technical Debt" 두 섹션에 각각 다른
문구로 세 번 반복돼 있어서, 이 문서만 보고 우선순위를 판단하면 이미 끝난
작업(Admin 키 설정)을 여전히 최우선 과제로 오판할 위험이 가장 컸다. Sprint 131/135와
같은 종류의 위험(이미 끝난 일이 할 일로 남아 다음 세션의 오탐/중복 작업을
유발)이 같은 문서(`docs/BETA_RELEASE_CHECKLIST.md`)에서만이 아니라
`docs/roadmap.md`에도 있었다는 것을 이번에 확인했다.

## 검증

| 항목 | 결과 |
|---|---|
| 코드 변경 | 0건(문서만) |
| `.env` 값 열람 | 0건(Secret 열람 금지 원칙 유지 — `os.getenv()` truthy 확인과 실 서버 응답 코드만 사용) |
| `docs/roadmap.md` 편집 | 5곳, 전부 취소선 + 정정 내용 추가(기존 서술 보존) |
| 관련 회귀 스위트 | 문서 전용 변경이라 재실행 불필요 |

## 수정 파일

```
docs/roadmap.md                  5개 항목 정정(취소선+정정 내용, 서술 보존)
docs/SPRINT139_ROADMAP_DRIFT.md  신규 (본 문서)
```

## SKIP

없음.

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112, 3일 남음).
- `docs/roadmap.md`의 "목록 엔드포인트 LIMIT 부재"(favorites/payments/registry-requests) —
  재확인 결과 지금도 정확한 기술부채(스테일 아님), 별도 Sprint 후보로 유지
- "등급 안에서 개별 운영자 식별" — 운영 인원 확장 시 필요한 제품 결정, 승인 영역
- Sprint 105~138 SKIP 표의 나머지 승인 대기 항목들
- 다음 Audit 영역: Transaction/Concurrency 나머지, Release Readiness, Dead Code
  2차, TODO/FIXME/HACK 2차 (계속 진행)
