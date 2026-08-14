# Sprint 118 ― 시간대 가드가 자기 주석만큼 넓지 않았다 (2026-08-14)

> 앞 Sprint: `docs/SPRINT117_PRESET_KEY_CONTRACT.md`
>
> **별도 파일 이유**: Sprint 100~117과 같다 ― `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

Sprint 101이 고친 UTC/로컬 혼용은 이 저장소에서 가장 조용한 결함이었다 ―
"30분 뒤 재시도"가 실제로는 9시간 30분이었고, 예외도 로그도 정상이었다.
그 재발을 막는 검사(`test_pipeline_integrity.py` §9)를 **다시 확인**했다.

---

## 주석이 약속한 것과 구현이 한 것

§9의 주석은 이렇게 못 박고 있다.

> 그래서 저장소의 **모든 추적 대상 `.py`를 본다. 예외를 두지 않는다** —
> 예외 목록은 곧 "여기만 UTC여도 된다"는 두 번째 규약이 되고, **그것이 이 결함의 뿌리다.**

그런데 구현은 몇 개 디렉터리만 훑고 있었다.

```
검사 대상 : PRODUCTION_PY 10개 + api/** + crawler/ + validator/ + normalizer/
            + filter/ + test_*.py
검사 밖   : 루트의 운영 스크립트 28개
            backfill_dong_normalize / repair_document_status / repair_empty_status_capture
            reset_failures / revalidate / migrate_dryrun / load_rights_data / load_spec_data
            unlock_retry / add_test_queue / config/ / models/ / intent/ ...
```

**전부 DB에 쓰는 스크립트다.** 하나라도 `datetime('now')` 를 쓰면 그 행만 UTC가 되고,
나머지 저장소 전체가 쓰는 로컬 시각과 9시간 어긋난다.

실측하니 **위반은 0건**이었다. 하지만 범위가 좁다는 사실 자체가
주석이 경고한 바로 그 "두 번째 규약"이다 ― 검사 밖에 있는 파일에는 규칙이 없는 것과 같다.

## 고친 것 ― 목록을 git에게 묻는다

```python
git ls-files --cached --others --exclude-standard *.py
```

추적 파일 + 아직 커밋되지 않은 새 파일을 얻고, `.gitignore` 대상인
`step*` / `check_*` / `patch_*` 일회성 조사 스크립트는 **자동으로 빠진다**.
새 파일이 생기면 다음 실행부터 곧바로 대상이 된다 ― 손으로 유지할 목록이 없다.

git이 없는 배포본에서는 예전 방식(디렉터리 훑기)으로 되돌아간다.

```
--- 9. SQLite 시각 비교가 로컬 시각인가 ---
    .py 107개 검사            <- 이전 약 75개
[PASS] 검사 대상 파일이 실제로 있다
[PASS] `now`를 쓰면서 localtime을 빠뜨린 자리 없음: []
```

전제 검사도 함께 조였다 ― `scanned > 5` 는 범위가 통째로 무너져도 통과한다.
git 목록이면 100개 안팎, 폴백이라도 40개는 넘으므로 **`> 40`** 으로 올렸다.
**검사가 조용히 좁아지는 것**은 이 세션에서 반복해 잡아 온 실패 모양이다
(Sprint 108의 `include_in_schema`, Sprint 109의 소프트 삭제 목록, Sprint 116의 진입점 목록).

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M95a | `reset_failures.py` 에 `datetime('now', '-1 day')` | **검출 O** ― `reset_failures.py:23` |
| M95b | `migrate_dryrun.py` 에 `date('now')` | **검출 O** ― `migrate_dryrun.py:21` |

**둘 다 넓히기 전에는 검사 밖이던 파일이다.** 넓힌 것이 값을 더했다는 직접 증거다.
원복 후 `_QA` 흔적 0건, 스위트 통과.

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **28/28 파일 통과** (실크롤 3개 제외) |
| `python -m compileall` | **exit 0** |
| 프런트 | 무변경 (Sprint 117에서 108/108, TSC/LINT/BUILD exit 0) |
| 실 DB | **한 줄도 쓰지 않았다** |

## 수정 파일

```
test_pipeline_integrity.py    §9의 검사 대상을 git 목록에서 유도 (75 -> 107개) + 전제 강화
```

**제품 코드 변경 0건.** 위반이 없었으므로 고칠 것도 없었다 ―
넓힌 것은 **앞으로 생길 위반을 잡는 범위**다.

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다.
  `register_scheduler_tasks.ps1 -Apply` 한 줄이면 된다(Sprint 112).
- Sprint 105~117의 SKIP 표 항목들 (전부 승인/외부 조치 대기)
