"""
intent.analyzer.analyze_intent() 단위 테스트.

Sprint 5 PRD(§7 회귀 테스트 계획)에서 정의한 대표 검색어를 기반으로 한다.
DB/API 의존성이 전혀 없는 순수 함수 테스트이므로 어떤 환경에서도 실행 가능하다.

실행: python test_intent_analyzer.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from intent.analyzer import analyze_intent, split_tokens, INTENT_LOT_NUMBER, \
    INTENT_FULL_ADDRESS, INTENT_SIDO, INTENT_SIGUNGU, INTENT_DONG, INTENT_MIXED, INTENT_UNKNOWN


CASES = [
    # (설명, 입력, 기대 intent, 기대 parsed 필드 일부 확인용 dict)
    ("시도(축약)", "서울", INTENT_SIDO, {"sido": "서울"}),
    ("시도(시)", "서울시", INTENT_SIDO, {"sido": "서울"}),
    ("시도(정식)", "서울특별시", INTENT_SIDO, {"sido": "서울"}),
    ("시군구", "송파구", INTENT_SIGUNGU, {"sigungu": "송파구"}),
    ("읍면동", "오금동", INTENT_DONG, {"dong": "오금동"}),
    ("전체주소", "서울 송파구 오금동", INTENT_FULL_ADDRESS,
     {"sido": "서울", "sigungu": "송파구", "dong": "오금동"}),
    ("혼합입력(시군구+동+일반명사)", "강서구 화곡동 빌라", INTENT_MIXED,
     {"sigungu": "강서구", "dong": "화곡동"}),
    ("건물명(인식불가)", "엘시티", INTENT_UNKNOWN, {"sido": "", "sigungu": "", "dong": ""}),
    ("지번", "19", INTENT_LOT_NUMBER, {"lot_number": "19"}),
    ("동명이인 시군구", "중구", INTENT_SIGUNGU, {"sigungu": "중구"}),
    ("STEP7에서 백필된 동", "성남동", INTENT_DONG, {"dong": "성남동"}),
    ("STEP7에서 백필된 동(2)", "빛가람동", INTENT_DONG, {"dong": "빛가람동"}),
    ("빈 문자열", "", INTENT_UNKNOWN, {}),
    # 시도 없이 시군구+동 2개 필드만 채워지는 경우(잔여 없음) — 3개 필드가 다 차야만
    # FULL_ADDRESS이므로, 이 케이스는 설계상 MIXED로 분류된다.
    ("시도 없는 시군구+동(일반구를 둔 시)", "고양시 일산동구 마두동", INTENT_MIXED,
     {"sido": "", "sigungu": "고양시 일산동구", "dong": "마두동"}),
]


def run():
    failures = []

    for name, text, exp_intent, exp_fields in CASES:
        result = analyze_intent(text)
        ok = result["intent"] == exp_intent
        for k, v in exp_fields.items():
            if result["parsed"].get(k) != v:
                ok = False

        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: {text!r} -> intent={result['intent']!r} residual={result['residual']!r}")
        if not ok:
            failures.append(name)
            print(f"    parsed={result['parsed']!r}")
            print(f"    기대 intent={exp_intent!r}, 기대 필드={exp_fields!r}")

    # residual 계산 자체를 별도로 검증(잔여 텍스트가 정확히 남는지)
    detail = analyze_intent("강서구 화곡동 빌라")
    ok = detail["residual"] == "빌라"
    print(f"[{'PASS' if ok else 'FAIL'}] residual 정확성 확인: residual={detail['residual']!r}")
    if not ok:
        failures.append("residual 정확성 확인")

    # split_tokens: 불용어/짧은 토큰 제외 확인
    tokens = split_tokens("고양시 마두동 아파트")
    ok = tokens == ["고양시", "마두동"]
    print(f"[{'PASS' if ok else 'FAIL'}] split_tokens 불용어 제외 확인: {tokens!r}")
    if not ok:
        failures.append("split_tokens 불용어 제외 확인")

    print()
    if failures:
        print(f"{len(failures)}건 실패: {failures}")
        return 1
    print(f"전체 {len(CASES) + 2}건 통과")
    return 0


if __name__ == "__main__":
    sys.exit(run())
