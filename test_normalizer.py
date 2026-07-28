"""
normalizer.normalize_address() 단위 테스트.

배경: 고양시/성남시/수원시 등 "일반구"를 둔 시는 기존 정규식이 구(區) 단위를
누락시켜, sigungu LIKE 검색에서 "일산동구" 같은 구 단위 검색이 영구히 0건이
되는 버그가 있었다 (Sprint: Search Upgrade Phase 1). 이 파일은 그 수정의
회귀 방지 테스트다. DB/storage 의존성이 전혀 없는 순수 함수 테스트이므로
개발환경(노트북)에서도 100% 실행 가능하다.

실행: python test_normalizer.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from normalizer.normalizer import normalize_address, extract_sido


CASES = [
    # (설명, 입력주소, 기대 sido, 기대 sigungu, 기대 dong)

    # --- 일반구를 둔 시: 이번 수정으로 고쳐진 케이스 ---
    ("고양시 일산동구", "경기도 고양시 일산동구 마두동 123-4", "경기", "고양시 일산동구", "마두동"),
    ("성남시 분당구", "경기도 성남시 분당구 정자동 100번지", "경기", "성남시 분당구", "정자동"),
    ("수원시 영통구", "경기도 수원시 영통구 매탄동 55-1", "경기", "수원시 영통구", "매탄동"),
    ("안양시 동안구", "경기도 안양시 동안구 관양동 300", "경기", "안양시 동안구", "관양동"),
    ("청주시 흥덕구", "충청북도 청주시 흥덕구 복대동 300", "충북", "청주시 흥덕구", "복대동"),
    ("포항시 남구", "경상북도 포항시 남구 대잠동 12", "경북", "포항시 남구", "대잠동"),
    ("전주시 완산구", "전라북도 전주시 완산구 효자동 50", "전북", "전주시 완산구", "효자동"),
    ("창원시 성산구", "경상남도 창원시 성산구 상남동 10", "경남", "창원시 성산구", "상남동"),

    # --- 회귀 방지: 기존에 정상이던 단일 레벨 구 (광역시 산하 자치구) ---
    ("서울 강남구 (회귀)", "서울특별시 강남구 역삼동 736-1", "서울", "강남구", "역삼동"),
    ("부산 해운대구 (회귀)", "부산광역시 해운대구 우동 1234", "부산", "해운대구", "우동"),

    # --- 회귀 방지: 구가 없는 군/읍 지역 (오탐 없어야 함) ---
    ("인천 강화군 (구 없음)", "인천광역시 강화군 불은면 신현리 100", "인천", "강화군", "불은면"),
    ("화성시 봉담읍 (구 없음)", "경기도 화성시 봉담읍 와우리 123", "경기", "화성시", "봉담읍"),

    # --- Sprint 3 STEP1: 도로명주소 + 괄호 안 법정동(콤마 바로 뒤따름) 케이스 ---
    # 실제 auction_item.full_address 샘플 기반 (콤마 뒤 lookahead 실패로 dong이
    # 빈 값이 되던 버그의 회귀 방지 테스트).
    ("송파구 문정동 (콤마, 공백없음)",
     "서울특별시 송파구 법원로4길 5 지2층비202호 (문정동,송파법조타운푸르지오시티) [집합건물 철근콘크리트구조 49.06㎡]",
     "서울", "송파구", "문정동"),
    ("양천구 신월동 (콤마+공백)",
     "서울특별시 양천구 남부순환로59길 7 제3층 제302호 (신월동, 토브하우스) [집합건물 철근콘크리트구조 29.06㎡]",
     "서울", "양천구", "신월동"),
    ("금천구 가산동 (콤마+공백)",
     "서울특별시 금천구 가산디지털1로 100 제9층 제908호 (가산동, 에이스골드타워) [집합건물 철근콘크리트구조 88.09㎡]",
     "서울", "금천구", "가산동"),

    # --- Sprint 4 STEP6: 괄호 앞 "건물동 라벨"/고유명사 오탐 회귀 방지 ---
    # 실제 auction_item.full_address 샘플 기반. 괄호 이전에 "OO동/리"로 끝나는
    # 건물동 표기나 고유명사가 있어도, 괄호 안 법정동을 우선해야 한다.
    ("송파구 오금동 (건물동 '에이동' 오탐 방지)",
     "서울특별시 송파구 동남로29길 4 에이동 2층204호 (오금동,센트럴오금) [집합건물 철근콘크리트조 92.48㎡]",
     "서울", "송파구", "오금동"),
    ("은평구 응암동 (건물동 '비동' 오탐 방지)",
     "서울특별시 은평구 은평로13길 12-12 비동 8층802호 (응암동,에스엠벨리체) [집합건물 철근콘크리트구조 25.59㎡]",
     "서울", "은평구", "응암동"),
    ("부천시 고강동 (건물동 '마동' 오탐 방지)",
     "경기도 부천시 오정구 지양로158번길 75-1 마동 지층 1호 (고강동, 성원빌라) [집합건물 벽돌조 40.98㎡]",
     "경기", "부천시 오정구", "고강동"),
    ("남양주시 별내동 (건물동 '판매시설동' 오탐 방지)",
     "경기도 남양주시 별내1로 6 판매시설동 2층205호 (별내동,힐스테이트별내역) [집합건물 철근콘크리트구조 64.9172㎡]",
     "경기", "남양주시", "별내동"),
    ("울산 중구 성남동 (고유명사 '젊음의거리' 오탐 방지 — 건물동 라벨이 아닌 일반 명칭 사례)",
     "울산광역시 중구 젊음의거리 20 3층301호 (성남동,울산호텔리버사이드) [집합건물 철근콘크리트구조 30.51㎡]",
     "울산", "중구", "성남동"),

    # --- 회귀 방지: 괄호가 아예 없는 주소는 기존 폴백 로직이 그대로 동작해야 함 ---
    ("괄호 없는 주소 (기존 폴백 로직 유지 확인)",
     "경기도 고양시 일산동구 마두동 123-4",
     "경기", "고양시 일산동구", "마두동"),

    # --- Bug Fix: 시도 축약형("-시")이 SIDO_PREFIXES 누락으로 sigungu로 오인식되던
    # 문제의 회귀 방지. 접두어가 안 지워지면 "서울시" 자체가 시군구 정규식에 매치되어
    # sigungu="서울시"가 되던 버그였다. ---
    ("시도 축약형 단독 (서울시)", "서울시", "서울", "", ""),
    ("시도 축약형 + 시군구 + 동 (서울시 송파구 오금동)",
     "서울시 송파구 오금동", "서울", "송파구", "오금동"),
    ("시도 축약형 + 시군구 (인천시 서구)", "인천시 서구", "인천", "서구", ""),
    ("시도 축약형 + 시군구 (부산시 해운대구)", "부산시 해운대구", "부산", "해운대구", ""),
    ("시도 축약형 단독, 시군구 계층 없음 (세종시)", "세종시", "세종", "", ""),
]


def run():
    failures = []

    for name, addr, exp_sido, exp_sigungu, exp_dong in CASES:
        result = normalize_address(addr)
        ok = (
            result["sido"] == exp_sido
            and result["sigungu"] == exp_sigungu
            and result["dong"] == exp_dong
        )
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: {addr}")
        if not ok:
            failures.append(name)
            print(f"    got      sido={result['sido']!r} sigungu={result['sigungu']!r} dong={result['dong']!r}")
            print(f"    expected sido={exp_sido!r} sigungu={exp_sigungu!r} dong={exp_dong!r}")

    # 부가 필드(lot_number, full_address)가 이번 수정과 무관하게 그대로 동작하는지 확인
    detail = normalize_address("서울특별시 강남구 역삼동 736-1")
    ok = detail["lot_number"] == "736-1" and detail["full_address"] == "서울특별시 강남구 역삼동 736-1"
    print(f"[{'PASS' if ok else 'FAIL'}] lot_number/full_address 부가필드 보존")
    if not ok:
        failures.append("lot_number/full_address 부가필드 보존")
        print(f"    got lot_number={detail['lot_number']!r} full_address={detail['full_address']!r}")

    # 빈 문자열 입력 시 예외 없이 빈 값 반환하는지 확인 (방어 코드 회귀 확인)
    try:
        empty = normalize_address("")
        ok = all(empty[k] == "" for k in ("sido", "sigungu", "dong", "lot_number"))
        print(f"[{'PASS' if ok else 'FAIL'}] 빈 문자열 입력 시 예외 없이 빈 값 반환")
        if not ok:
            failures.append("빈 문자열 입력 처리")
    except Exception as e:
        failures.append("빈 문자열 입력 처리")
        print(f"[FAIL] 빈 문자열 입력 시 예외 발생: {e!r}")

    # extract_sido 자체 회귀 확인 (normalize_address가 내부적으로 의존)
    ok = extract_sido("세종특별자치시 어진동 100") == "세종"
    print(f"[{'PASS' if ok else 'FAIL'}] extract_sido 단독 동작 확인")
    if not ok:
        failures.append("extract_sido 단독 동작")

    print()
    if failures:
        print(f"{len(failures)}건 실패: {failures}")
        return 1
    print(f"전체 {len(CASES) + 3}건 통과")
    return 0


if __name__ == "__main__":
    sys.exit(run())
