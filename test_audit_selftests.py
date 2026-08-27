# -*- coding: utf-8 -*-
"""감사 도구의 `--selftest` 를 회귀 스위트에서 실제로 돌린다 (2026-08-24 Sprint 251 신설).

## 왜 이 파일이 생겼나

이 저장소의 감사 도구 세 개는 자기 자신을 검사하는 `--selftest` 를 갖고 있다.
그런데 **그 selftest 를 돌리는 것이 아무것도 없었다.**

    run_python_tests.py   `test_*.py` 만 찾는다 -> audit_*.py 는 대상이 아니다
    .bat / .ps1           `--selftest` 참조 0건 (2026-08-24 실측)
    package.json          프런트 전용

즉 감사기가 조용히 눈이 멀어도(쿼리가 바뀌거나 경로 규칙이 달라져서) 아무도 모른다.
그것은 감사기가 막으려던 상태 그 자체다 — `audit_asset_integrity.py` 의 selftest
docstring 이 직접 그렇게 적어 두었다: *"감사 스크립트는 조용히 눈이 멀기 쉽다 ...
그리고 그 상태는 정상과 겉으로 완전히 같다."*

## 왜 지금 옮겨도 되나 (예전에는 안 됐다)

`audit_asset_integrity.py` 의 selftest 는 **회귀 스위트가 아니라 자기 파일 안에**
있었고, 그 이유를 이렇게 적어 두었다:

    "이 파일은 아직 **미추적 파일**이고(`git add` 는 승인 영역), 추적된 테스트가
     미추적 파일을 import 하면 커밋 시 부팅이 깨진다(BUGS #105).
     ... 파일이 추적되면 그때 회귀 스위트로 옮기는 것이 맞다."

2026-08-24 실측: 세 파일 다 **이미 추적된다**(`git ls-files` 확인).
그래서 그 조건이 스스로 말한 대로 충족됐다.

## import 하지 않고 **서브프로세스로** 돈다

세 도구는 모듈 수준에서 `.env` 를 읽고 DB 경로를 잡는다. import 로 끌어오면 이 파일이
그 부작용을 떠안고, 한 도구의 전역 상태가 다른 도구에 샌다. 별도 프로세스로 돌리면
종료 코드만 계약으로 남는다 — 이 저장소가 `run_python_tests.py` 에서 이미 택한 판단과
같다("판정은 출력 문구가 아니라 종료 코드로").

## 무엇을 하지 않는가

`--selftest` 가 **아닌** 실행은 하지 않는다. 그쪽은 운영 DB 를 훑고(느리다),
`audit_auth_health.py` 는 외부 네트워크 요청까지 보낸다 — 회귀 스위트가 승인 없이
외부 서비스를 두드리면 안 된다. selftest 는 전부 스크래치/가짜 데이터만 쓴다.

    python test_audit_selftests.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
failures = []


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name,
                         ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


# 여기 적은 도구는 전부 "selftest 는 아무것도 바꾸지 않는다"를 자기 docstring 으로
# 약속한 것들이다. 새 도구에 --selftest 를 만들면 이 표에 추가한다.
TOOLS = [
    "audit_asset_integrity.py",
    "audit_schedule_health.py",
    "audit_auth_health.py",
    # 2026-08-27 추가 (BUGS #258) - 이 도구는 "다른 검사가 공허하지 않은가"를 재면서
    #   **정작 자기 자신은 아무도 재지 않았다.** 그리고 이 도구가 틀렸을 때 나오는 것은
    #   오류가 아니라 **그럴듯한 숫자**라 조용히 틀린다:
    #     - 저장소 경로가 다른 PC 것으로 박혀 있어 한 줄도 돌지 않았다(#252)
    #     - coverage 출력이 비면 이유 없이 None 으로 사라졌다(#258)
    #   둘 다 selftest 를 붙이면서 드러났다.
    "audit_test_reality.py",
]


def test_tools_are_tracked():
    """추적되지 않는 파일을 이 테스트가 실행하면 커밋 후 부팅이 깨진다(BUGS #105 계열).

    실행은 import 가 아니라 서브프로세스지만, **파일이 없으면 이 테스트가 실패한다**는
    점은 같다. 그래서 추적 여부를 먼저 확인한다 — 못 물어보면(git 없음) 건너뛴다.
    """
    print("\n--- 감사 도구가 추적 대상인가 ---")
    try:
        p = subprocess.run(["git", "ls-files", "--"] + TOOLS,
                           cwd=ROOT, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        print("    (git 을 실행할 수 없어 건너뛴다)")
        return
    if p.returncode != 0:
        print("    (git 저장소가 아니라 건너뛴다)")
        return
    tracked = set((p.stdout or b"").decode("utf-8", "replace").split())
    for t in TOOLS:
        check_true("%s 가 추적된다" % t, t in tracked,
                   "-> 추적되지 않은 파일에 회귀 스위트가 의존하면 안 된다")


def test_selftests_pass():
    print("\n--- 감사 도구 --selftest ---")
    check_true("검사가 공허하지 않다(도구 목록이 비어 있지 않다)", len(TOOLS) >= 3, TOOLS)
    for tool in TOOLS:
        path = os.path.join(ROOT, tool)
        if not os.path.exists(path):
            check_true("%s 가 있다" % tool, False, path)
            continue
        # 자식이 한글을 찍다 cp949 로 죽지 않게 한다(이 저장소의 알려진 함정).
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            p = subprocess.run([sys.executable, path, "--selftest"],
                               cwd=ROOT, capture_output=True, timeout=600, env=env)
        except subprocess.TimeoutExpired:
            check_true("%s --selftest 가 시간 안에 끝난다" % tool, False, "600초 초과")
            continue
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
        ok = p.returncode == 0
        check_true("★ %s --selftest 통과" % tool, ok,
                   "-> exit=%s\n%s" % (p.returncode, (out or err)[-1500:]))
        # 종료코드 0 인데 아무 판정도 안 찍혔으면 "통과"가 아니라 **실행되지 않은 것**이다
        # (run_python_tests.py 의 NO-VERDICT 와 같은 구분).
        if ok:
            check_true("%s --selftest 가 실제로 판정을 찍었다" % tool,
                       ("[PASS]" in out) or ("통과" in out),
                       "-> 출력에 판정문이 없다:\n%s" % out[-800:])


def run():
    test_tools_are_tracked()
    test_selftests_pass()
    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
