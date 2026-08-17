"""`documents/` 아래의 **빈 디렉터리**를 찾아서 보여준다 (2026-08-17 Sprint 144 신설).

`cleanup_orphans_dryrun.py`와 형제 스크립트이고 같은 관례를 따른다 —
**아무것도 지우지 않는다. `--apply` 옵션도 없다.** `documents/` 아래를 지우는 것은
운영 판단이므로, 여기서는 "무엇이 비어 있고 / 왜 생겼고 / 지우면 무엇을 잃는지"를
정확히 만들어 두는 데까지만 한다.

## 두 스크립트의 차이 (겹치지 않는다)

    cleanup_orphans_dryrun.py   "대응 auction_item이 **없는**" 디렉터리 (고아)
    이 스크립트                  "auction_item은 **있는데** 파일이 하나도 없는" 디렉터리

후자가 훨씬 많다. 2026-08-17 실측에서 **1,681개**였다.

## 어디서 생겼나

`crawler/doc_paths.py:doc_exists()`가 예전에 `get_doc_dir()`를 불렀고, 그 함수는
`os.makedirs()`를 한다. 즉 **"이 문서 있어요?"라고 묻기만 해도 디스크에 3단계
디렉터리(법원/사건/물건)가 생겼다.** 그 코드는 2026-08-14에 고쳐졌지만
(`_doc_dir_path()`로 조회와 생성을 분리) **이미 만들어진 디렉터리는 그대로 남아 있다.**

## 지우면 무엇을 잃나 — 아무것도 잃지 않는다. 그래도 자동으로 지우지 않는 이유

빈 디렉터리에는 파일이 0개이므로 데이터 손실이 없다. 그런데도 `--apply`를 두지 않는
이유는 두 가지다:

  1. **아직 수집 중인 물건의 자리일 수 있다.** 지워도 다음 수집이 `get_doc_dir()`로
     다시 만들므로 기능 영향은 없지만, 지우는 동안 worker가 같은 경로에 쓰고 있으면
     경합이 생긴다. 안전한 시점(worker 미실행)은 운영자가 안다.
  2. 이 저장소의 규약이다 — `documents/` 아래를 건드리는 파괴적 동작에는 승인이 필요하다.

## 안전한 삭제 절차 (운영자용)

    1) doc_worker.py가 실행 중이 아닌지 확인 (logs/doc_worker.lock 없음)
    2) python empty_doc_dirs_dryrun.py   <- 목록과 건수 확인
    3) 아래 출력의 PowerShell 한 줄을 그대로 실행

    python empty_doc_dirs_dryrun.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
DOCUMENT_ROOT = os.path.join(ROOT, "documents")


def scan():
    """(빈 물건 디렉터리, 빈 사건 디렉터리, 빈 법원 디렉터리)를 각각 돌려준다.

    아래에서 위로 본다 — 물건 디렉터리를 지우면 사건 디렉터리가 비고, 그러면 그것도
    지울 수 있다. 한 번의 스캔으로 세 단계를 다 계산해 둔다.
    """
    empty_items, empty_cases, empty_courts = [], [], []
    if not os.path.isdir(DOCUMENT_ROOT):
        return empty_items, empty_cases, empty_courts

    for court in sorted(os.listdir(DOCUMENT_ROOT)):
        court_path = os.path.join(DOCUMENT_ROOT, court)
        if not os.path.isdir(court_path):
            continue
        court_has_content = False

        for case in sorted(os.listdir(court_path)):
            case_path = os.path.join(court_path, case)
            if not os.path.isdir(case_path):
                court_has_content = True
                continue
            case_has_content = False

            for item in sorted(os.listdir(case_path)):
                item_path = os.path.join(case_path, item)
                if not os.path.isdir(item_path):
                    case_has_content = True
                    continue
                # 물건 디렉터리 안에 파일이 하나라도 있으면(하위 images/ 포함) 비지 않은 것이다.
                has_file = any(files for _, _, files in os.walk(item_path))
                if has_file:
                    case_has_content = True
                else:
                    empty_items.append(item_path)

            if case_has_content:
                court_has_content = True
            else:
                empty_cases.append(case_path)

        if not court_has_content:
            empty_courts.append(court_path)

    return empty_items, empty_cases, empty_courts


def main():
    print("=" * 74)
    print("documents/ 빈 디렉터리 점검 (DRY-RUN - 아무것도 지우지 않는다)")
    print("=" * 74)

    if not os.path.isdir(DOCUMENT_ROOT):
        print("  documents/ 디렉터리가 없다. 점검할 것이 없다.")
        return 0

    items, cases, courts = scan()

    total_dirs = 0
    total_files = 0
    for _, dirs, files in os.walk(DOCUMENT_ROOT):
        total_dirs += len(dirs)
        total_files += len(files)

    print("\n1. 현재 규모")
    print("   전체 디렉터리      : %d" % total_dirs)
    print("   전체 파일          : %d" % total_files)

    print("\n2. 비어 있는 디렉터리")
    print("   물건 디렉터리(파일 0개) : %d" % len(items))
    print("   그로 인해 비는 사건 디렉터리 : %d" % len(cases))
    print("   그로 인해 비는 법원 디렉터리 : %d" % len(courts))

    if items:
        print("\n   예시 (앞 15개):")
        for p in items[:15]:
            print("     " + os.path.relpath(p, ROOT))
        if len(items) > 15:
            print("     ... 외 %d개" % (len(items) - 15))

    print("\n3. 원인")
    print("   `crawler/doc_paths.py:doc_exists()`가 예전에 조회하면서 `os.makedirs()`를")
    print("   부른 흔적이다(2026-08-14에 조회/생성을 분리해 원인 코드는 이미 고쳐졌다).")
    # cp949 콘솔에서 인코딩할 수 없는 문자(EM DASH 등)를 print에 넣지 않는다 —
    # `test_console_encoding.py`가 이 파일을 전수 스캔한다(Sprint 72/133).
    print("   지금은 새로 늘지 않는다 - 아래 회귀 검사가 그것을 고정한다:")
    print("     test_asset_pipeline.py  '조회만으로 디렉터리가 생기지 않는다'")

    print("\n4. 위험도")
    print("   파일이 0개이므로 **데이터 손실 없음**. 지워도 다음 수집이 필요할 때 다시 만든다.")
    print("   다만 worker 실행 중에는 같은 경로에 쓰고 있을 수 있으므로 시점만 주의한다.")

    print("\n5. 삭제 절차 (운영자 판단 - 이 스크립트는 실행하지 않는다)")
    print("   1) logs/doc_worker.lock 이 없는지 확인 (worker 미실행)")
    print("   2) 아래 명령을 실행")
    print()
    print("      powershell -Command \"Get-ChildItem -Path 'documents' -Recurse -Directory |"
          " Sort-Object -Property FullName -Descending |"
          " Where-Object { -not (Get-ChildItem $_.FullName -Recurse -File) } |"
          " Remove-Item -Force\"")
    print()
    print("   (FullName 내림차순 정렬이 중요하다 - 깊은 것부터 지워야 부모가 비면서 함께 정리된다)")

    print("\n6. 결론")
    print("   이 스크립트는 아무것도 지우지 않았다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
