# Sprint 124 ― Dependency Audit + Dead Code 탐색 (2026-08-15)

> 앞 Sprint: `docs/SPRINT123_SEARCH_SORT_TIEBREAK.md`
>
> **별도 파일 이유**: Sprint 100~123과 같다.

## ★ 2026-08-15 정정 (Sprint 125)

아래 §1의 "전부 빌드 툴체인, 런타임 공격 표면 없음" 결론은 **`npm audit`의 축약
출력만 보고 내린 것이라 불완전했다.** `npm audit fix --dry-run`으로 전체 출력을
다시 보니 **Next.js 자체의 취약점 9건**이 별도로 있었고, 그중 2건(Server Action
관련 미인증 DoS/정보노출, CVSS 최대 8.2)은 이 저장소의 실제 설정에 그대로
적용된다 — postcss/sharp/brace-expansion과 달리 "이 앱은 그 기능을 안 쓴다"로
넘길 수 없다. 상세 재조사와 정확한 최소 수정 버전(`next@16.2.11`, `16.3.1`이
아니다)은 `docs/SPRINT125_NEXTJS_CVE_CORRECTION.md`를 본다. §1 아래 내용은
postcss/brace-expansion/sharp/@tailwindcss postcss에 대한 결론으로는 여전히
유효하다(그 부분은 뒤집히지 않았다) — next 자체의 결론만 교체됐다.

## 1. `npm audit` ― 7건(1 moderate / 6 high), 전부 빌드 툴체인 - 승인 대기로 SKIP

```
brace-expansion   high (DoS, glob 확장)      - eslint 등 빌드 도구의 전이 의존성
postcss           high (XSS/경로탐색)         - Tailwind 빌드 시점 CSS 처리, next 내부 의존성
@tailwindcss/postcss  moderate               - 위 postcss에 의존
sharp             high (libvips CVE 4건)     - next/image 최적화용, 이 저장소는 next/image 미사용
```

실사용자 공격 표면 재확인: `grep -rn "next/image|sharp" src/` 결과 `next/image` 컴포넌트를
쓰는 곳이 **0곳**이다(`src/proxy.ts`의 matcher 정규식에 `_next/image` 문자열이 있을 뿐,
실제로 이미지 최적화 파이프라인을 호출하지 않는다). `sharp`는 next의 선택적 의존성으로만
설치돼 있고, 이 앱은 사용자 업로드 이미지를 처리하지 않는다. `postcss`/`brace-expansion`도
빌드 시점 도구 체인(Tailwind CSS 컴파일, eslint의 glob 매칭)이라 런타임에 공격자가 제어하는
입력이 닿지 않는다.

수정하려면 `npm audit fix --force`가 필요한데 **"Will install next@16.3.1, which is outside
the stated dependency range"** ― `package.json`이 선언한 범위 밖 메이저 업그레이드다.
`docs/CLAUDE.md`의 "새 라이브러리 설치는 승인 후"에 해당해 SKIP한다. 실행하지 않았다
(dry-run 성격의 `npm audit`만 실행, `--fix`/`--force`는 실행 안 함).

## 2. `unlock_retry.py` ― 안전장치 없이 하드코딩된 사건번호에 직접 쓰는 추적 파일

```python
conn.execute("""
    UPDATE document_queue SET last_attempt_at = NULL
    WHERE case_no = '2024타경1775' AND doc_type = 'appraisal'
""")
conn.commit()
```

- **저장소 전체에서 참조 0건**(`grep -rn "unlock_retry"` 결과 이 파일 자기 자신뿐) ― 죽은 코드.
- `.gitignore`가 `step*.py`/`check_*.py`/`patch_*.py`는 스크래치로 분류해 무시하는데, 이
  파일은 그 명명 규칙을 안 따라서 **git이 추적하고 있다**(`git ls-files unlock_retry.py`
  확인) ― 즉 커밋된 "정식 코드"처럼 보이지만 실제로는 2026년 어느 날의 사건번호 하나에
  대한 1회성 수동 조치다.
- 이 저장소의 다른 모든 복구/백필 스크립트(`backfill_region_normalize.py`,
  `repair_unsupported_status_docs.py`, `cleanup_orphans_dryrun.py`, `reset_failures.py`
  등)는 예외 없이 **기본이 dry-run이고 `--apply`가 있어야 실제로 쓴다.** 이 파일만 그
  관례 밖에서 **가드 없이 즉시 `commit()`한다.**
- 실측: 지금도 `document_queue`에 `case_no='2024타경1775' AND doc_type='appraisal'`이
  **1행 존재한다** ― 즉 이 스크립트는 지금 실행해도 완전한 no-op이 아니라 실제로 그
  한 행의 `last_attempt_at`을 지운다(재시도 대기 타이머를 초기화). 죽은 코드지만 실행하면
  아직 부작용이 있다.

삭제는 승인 영역(`docs/CLAUDE.md`: "사용 여부가 확실하지 않은 코드는 임의로 삭제하지
않는다" + "승인 없는 파일 삭제 금지")이라 이 세션에서는 지우지 않는다. 발견 사실만
기록한다 ― 정리하려면: (a) 이미 목적을 다한 1회성 조치이므로 삭제, 또는 (b) 계속 쓸
운영 도구라면 다른 스크립트와 같은 dry-run/`--apply` 관례로 재작성.

## 3. ★★ `fix_validator.py` ― 같은 패턴의 두 번째 사례, 그리고 이건 지금도 활성 위험이다

"동일 패턴이 다른 파일에도 있는가"를 전수로 찾다가(`git ls-files | grep commit()`)
`unlock_retry.py`와 **완전히 같은 반사회적 패턴**을 하나 더 찾았다 ― 이쪽이 더 심각하다.

```python
# fix_validator.py (전문에 가까움)
conn.execute("""
    UPDATE auction
    SET validation_status = 'PASS', validation_reasons = ''
    WHERE case_no = '2024타경653'
""")
conn.commit()
```

- **저장소 전체 참조 0건**(`grep -rn "fix_validator"` 결과 자기 자신뿐) ― 죽은 코드,
  gitignore 관례(`step*`/`check_*`/`patch_*`) 밖이라 git이 추적한다(`unlock_retry.py`와
  같은 상태).
- **`--apply`/dry-run 게이트가 아예 없다.** 임포트하자마자 무조건 `commit()`한다 —
  이 파일을 실행하는 순간(예: import 부작용을 모르고 `python fix_validator.py`) 즉시 쓴다.
- **지금 실행하면 실제로 결함을 만든다.** 이 case_no(`2024타경653`)를 실측 조회한 결과
  오늘도 `validation_status='FAIL'`이고 사유는 `address_mismatch: addr=경북 appraisal=경기`다
  ― `docs/SPRINT103_NORMALIZER_DRIFT.md`/`SPRINT114_FALSE_VALIDATION_FAIL.md`가 정리한
  **알려진 오탐 2건**(`2025타경513824-1`, `2016타경3104-1`) 목록에도 없다. 즉 지금 이
  스크립트를 실행하면 **아직 검증되지 않은(어쩌면 진짜인) 데이터 불일치를 근거 없이
  PASS로 덮어쓴다** ― 이 세션 전체가 계속 찾아 온 "False Success"를 스크립트 하나가
  그대로 만들어 낼 수 있는 상태다.

`unlock_retry.py`와 이 파일 둘 다 같은 근본 원인을 가리킨다 ― **과거 세션이 특정 사건
하나를 손으로 고치려고 만든 스크립트를, 그 조치가 끝난 뒤 지우지 않고 커밋했다.**
둘 다 이름이 `check_*`/`step*`/`patch_*` gitignore 관례를 따르지 않아 "일회성 스크래치"로
분류되지 않고 저장소에 정식 코드처럼 남아 있다.

### 3-B. 세 번째 사례 ― `add_test_queue.py`, 그리고 이 셋이 같은 사건을 가리킨다

같은 패턴을 저장소 루트의 **추적되는 `.py` 파일 전수**(gitignore 관례를 따르지 않는
`step*`/`check_*`/`patch_*` 밖의 모든 것, 29개)로 넓혀 대조했다. `.commit()` 보유 여부와
사건번호 하드코딩 여부를 각각 확인한 결과 세 번째 사례를 찾았다.

```python
# add_test_queue.py (전문)
from storage.database import init_db, enqueue_documents

init_db()
enqueue_documents([{
    'court_code': '서울중앙지방법원',
    'case_no': '2024타경1775',
    'auction_date': '2026-07-15'
}])
print("큐에 넣기 완료")
```

**`unlock_retry.py`와 정확히 같은 사건번호(`2024타경1775`)다** ― 세 스크립트가 같은
디버깅 세션의 산출물임을 강하게 시사한다: 큐에 못 들어간 사건을 수동으로 넣고
(`add_test_queue.py`) → 재시도 잠금을 풀고(`unlock_retry.py`) → (별개 세션으로 보이는)
검증 실패를 수동으로 지운 것(`fix_validator.py`, 사건번호는 다르다 `2024타경653`).

심각도는 셋이 다르다 ― `enqueue_documents()`는 정식 함수이고 `document_queue`의
`UNIQUE(court_code, case_no, item_no, doc_type)`가 중복 삽입을 막아 주므로, 재실행해도
기존 큐 상태를 깨지는 않는다(가장 안전). `unlock_retry.py`는 재시도 타이머만 되돌린다
(중간). `fix_validator.py`는 검증 결과 자체를 조작한다(가장 위험, §3 참고).

**그 외 26개 추적 스크립트는 전부 안전하다** ― 나머지는 (a) `.commit()`이 아예 없는
읽기 전용 도구(`analyze_*.py`, `migrate_check.py`, `migrate_dryrun.py`, `verify_*.py`,
`revalidate.py`, `measure_endless_collecting.py`, `manual_test.py`)이거나 (b) 이미
`--apply` 게이트를 가진 정식 운영 도구(§1에서 확인한 backfill/repair 계열)이거나
(c) 하드코딩된 단일 대상 없이 일반 배치로 동작하는 메인 파이프라인
(`api_server.py`/`mvp_scraper.py`/`doc_worker.py`/`migrate_execute.py`/
`refresh_priority.py`/`collect_documents.py`/`load_rights_data.py`/`load_spec_data.py`)다.
이 세 개(`unlock_retry.py`/`fix_validator.py`/`add_test_queue.py`)로 이 패턴은 완결된다.

## 검증

| 항목 | 결과 |
|---|---|
| `npm audit` | 7건 확인(전부 빌드 툴체인, 런타임 공격 표면 없음), 수정 미실행 |
| `unlock_retry.py` 실행 여부 | 실행하지 않았다(발견만) ― 실행하면 실 데이터 1행에 부작용이 있음을 확인했을 뿐 |
| `fix_validator.py` 실행 여부 | 실행하지 않았다(발견만) ― 대상 case_no가 지금도 실제로 FAIL 상태임을 읽기 전용 조회로만 확인 |
| `add_test_queue.py` 실행 여부 | 실행하지 않았다(발견만) |
| 동일 패턴(ungated 직접 commit 스크립트) 전수 검색 | 루트의 추적 `.py` 29개 전수(§3-B) - `.commit()` 보유 + 사건번호 하드코딩 여부 대조, 3건 확정, 나머지 26건은 안전 확인 |
| 실 DB | 한 줄도 쓰지 않았다(전부 읽기 전용 조회) |

## 수정 파일

```
docs/SPRINT124_DEPENDENCY_DEADCODE_AUDIT.md   신규 (본 문서)
```

제품 코드/테스트 변경 없음 ― 이번 라운드는 순수 감사(발견 기록)다.

## SKIP (사용자/제품 결정 필요)

| 항목 | 이유 |
|---|---|
| `npm audit fix --force` (next 메이저 업그레이드) | 선언 범위 밖 새 라이브러리 버전 설치 - 승인 영역 |
| `unlock_retry.py` 삭제 또는 재작성 | 파일 삭제/정리는 승인 영역 |
| `fix_validator.py` 삭제 또는 재작성 | 파일 삭제/정리는 승인 영역 - **우선순위가 더 높다**(§3, 지금 실행하면 실제 데이터 오염) |
| `add_test_queue.py` 삭제 또는 재작성 | 파일 삭제/정리는 승인 영역 - 셋 중 위험도는 가장 낮음(§3-B) |
| `2024타경653`의 `address_mismatch`가 진짜 결함인지 판정 | 이 case_no 자체를 조사(정규화 결과가 맞는지, 감정요항 원문을 봐야 하는지)하는 것은 별도 작업 - 이 세션에서는 "스크립트가 위험하다"만 확인했고 그 사건 자체의 데이터 진위는 조사하지 않았다 |

## 남은 Backlog

- Sprint 105~123의 SKIP 표 항목들 (전부 승인/외부 조치 대기, 미해소)
