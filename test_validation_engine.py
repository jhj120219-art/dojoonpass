"""ValidationEngine.validate() 회귀 테스트 (2026-08-13 Sprint 78 신설).

## 왜 지금 만드는가 — 커버리지가 지목했다

전체 스위트를 커버리지로 돌려 보니 `validator/validation_engine.py`가 **52%**이고,
미커버 구간(47-131)이 `validate()` **전체**였다. 즉 이 파일에서 실제로 판정을 하는 코드는
한 번도 실행된 적이 없다.

## 왜 위험한가

`validate()`가 정하는 `validation_status`는 그 자리에서 끝나지 않는다.

    ValidationEngine.validate()  ->  AuctionItem.validation_status
      -> normalize_item()        ->  upsert_batch()  ->  auction / auction_item
        -> GET /api/v1/search?validation_status=...  (검색 필터)
        -> GET /api/v1/item/{id} 의 validation_status 필드 (화면 표시)

규칙 하나가 어긋나면 **정상 물건이 "검증실패"로 표시되거나**, 반대로 사건번호 형식이 깨진
물건이 PASS로 흘러간다. 어느 쪽도 예외를 던지지 않으므로 로그로도 드러나지 않는다.

게다가 이 파일은 **2026-08-13 Sprint 78에 수정됐다** — `extract_sido` 복사본을 없애고
`normalizer`의 것을 재노출하도록 바꿨다. 그 주석이 위험을 정확히 적어 두었다:
"normalizer 쪽 판정 규칙을 고쳤을 때 이 복사본을 그대로 뒀다면 크롤 데이터는 제주로
저장되는데 검증은 세종으로 판정하는 상태가 됐을 것이다." 그런 변경을 **검사 0건 상태에서**
한 것이 이 파일을 만든 직접적인 이유다.

## 무엇을 고정하는가

현재 구현이 이미 가진 규칙만 고정한다(새 정책을 정하지 않는다).

    1) 필수 필드 4종 누락(case_no/address/appraisal_price/auction_date) -> FAIL + 사유
    2) 주소 시도 != 감정요항 시도 -> FAIL, 단 인접 쌍(서울-경기 등)은 허용
    3) 최저가 > 감정가 + 1000원 -> FAIL (오차 이내는 통과)
    4) 사건번호가 `\\d{4}타경\\d+` 형식이 아니면 FAIL
    5) 사유가 하나도 없으면 PASS
    6) 로그 기록 실패가 검증 자체를 죽이지 않는다 (관측이 본 작업을 방해하지 않는다)

DB/네트워크/selenium 의존이 없는 순수 로직이다. 로그는 임시 디렉터리로만 쓴다.
출력은 ASCII만 사용한다(Windows cp949 콘솔 대비 — 이 저장소의 기존 규약).

    python test_validation_engine.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.auction_item import AuctionItem
from validator.validation_engine import (
    ADJACENT_SIDO_PAIRS, PRICE_TOLERANCE, ValidationEngine, is_adjacent, parse_price,
)

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


def item(**over):
    """기본이 **PASS인** 물건. 각 검사는 고치려는 필드만 덮어쓴다.

    기본값이 FAIL이면 "무엇 때문에 실패했는지"를 검사마다 다시 증명해야 한다.
    """
    base = dict(
        case_no="2024타경1234", item_no="1",
        address="서울특별시 강남구 역삼동 736-1", property_type="아파트",
        appraisal_price="1,000,000,000", minimum_bid_price="800,000,000",
        auction_date="2026-09-01", status="유찰",
        court_code="서울중앙지방법원", court_name="서울중앙지방법원",
        appraisal_summary="서울특별시 강남구 역삼동 일대 아파트",
    )
    base.update(over)
    return AuctionItem(**base)


def reasons_of(engine, it):
    result = engine.validate(it)
    return result.validation_status, list(result.validation_reasons)


def main():
    tmp = tempfile.mkdtemp(prefix="qa_validation_")
    engine = ValidationEngine(log_path=os.path.join(tmp, "validation.jsonl"))
    try:
        # --- 1. 정상 물건은 PASS (기준선) ---------------------------------------
        print("\n--- 1. 정상 물건 ---")
        status, reasons = reasons_of(engine, item())
        check("정상 물건은 PASS", status, "PASS")
        check("정상 물건은 사유가 없다", reasons, [])

        # --- 2. 필수 필드 누락 --------------------------------------------------
        print("\n--- 2. 필수 필드 누락 ---")
        REQUIRED = [
            ("case_no", "case_no missing"),
            ("address", "address missing"),
            ("appraisal_price", "appraisal_price missing"),
            ("auction_date", "auction_date missing"),
        ]
        for field_name, expected_reason in REQUIRED:
            # 크롤러는 값이 없을 때 "-"를 넣는다(court_crawler.py의 기본값) — 빈 문자열과
            # "-" 둘 다 누락으로 봐야 한다. 두 형태를 모두 확인한다.
            for empty in ("", "-"):
                status, reasons = reasons_of(engine, item(**{field_name: empty}))
                check("%s=%r -> FAIL" % (field_name, empty), status, "FAIL")
                check_true("%s=%r 사유가 정확하다" % (field_name, empty),
                           expected_reason in reasons, reasons)

        # 여러 개가 동시에 비면 사유가 **모두** 남아야 한다(하나만 남기면 원인을 놓친다).
        status, reasons = reasons_of(engine, item(case_no="", address=""))
        check("동시 누락 시 FAIL", status, "FAIL")
        check_true("동시 누락 사유가 둘 다 남는다",
                   "case_no missing" in reasons and "address missing" in reasons, reasons)

        # --- 3. 주소 vs 감정요항 지역 불일치 ------------------------------------
        print("\n--- 3. 지역 불일치 ---")
        # 인접하지 않은 쌍: 서울 주소 + 부산 감정요항
        status, reasons = reasons_of(engine, item(appraisal_summary="부산광역시 해운대구 우동"))
        check("인접하지 않은 지역 불일치 -> FAIL", status, "FAIL")
        check_true("불일치 사유에 양쪽 시도가 적힌다",
                   any(r.startswith("address_mismatch") and "addr=서울" in r and "appraisal=부산" in r
                       for r in reasons), reasons)

        # 인접 쌍은 허용된다(서울-경기). 이 허용이 사라지면 정상 물건이 대량 FAIL이 된다.
        status, reasons = reasons_of(engine, item(appraisal_summary="경기도 성남시 분당구 정자동"))
        check("인접 쌍(서울-경기)은 PASS", status, "PASS")
        check_true("인접 쌍에는 불일치 사유가 없다",
                   not any(r.startswith("address_mismatch") for r in reasons), reasons)

        # BUGS #92 회귀 — 도로명에 섞인 지역명이 **가짜 불일치**를 만들면 안 된다.
        #
        # 수정 전에는 `extract_sido()`가 문자열 전체를 훑어 사전 순서로 첫 일치를 돌려줬다.
        # 그래서 "경기도 시흥시 **서울**대학로"의 주소가 addr=서울로 뽑혔고, 감정요항(경기)과
        # 어긋나 **멀쩡한 물건에 "검증실패"가 붙었다**. `서울대학로`/`부산대학로`는 실재하는
        # 도로명이라 이 상황은 재발한다.
        #
        # 이 검사는 validator 규칙이 아니라 **상류(normalizer)의 회귀**를 여기서 잡는다 —
        # 실제로 화면에 "검증실패"로 드러나는 자리가 여기이기 때문이다.
        status, reasons = reasons_of(engine, item(
            address="경기도 시흥시 서울대학로 59-21 1층189호",
            appraisal_summary="경기도 시흥시 정왕동"))
        check_true("도로명에 섞인 지역명이 가짜 불일치를 만들지 않는다(BUGS #92)",
                   not any(r.startswith("address_mismatch") for r in reasons), reasons)
        check("그 물건은 PASS", status, "PASS")

        # 건물명(뉴서울아파트) / 공유자 이름(뉴세종하우징)도 같은 부류다 — 실제로 오분류됐던
        # 네 건 중 두 건이 이 형태였다.
        status, reasons = reasons_of(engine, item(
            address="인천광역시 계양구 새벌로 88 303동 106호 (효성동, 뉴서울아파트)",
            appraisal_summary="인천광역시 계양구 효성동"))
        check_true("건물명에 섞인 지역명도 가짜 불일치를 만들지 않는다",
                   not any(r.startswith("address_mismatch") for r in reasons), reasons)

        # 선언된 인접 쌍 전부가 실제로 허용되는지 본다 — 목록과 판정이 갈라지면 안 된다.
        for pair in ADJACENT_SIDO_PAIRS:
            a, b = tuple(pair)
            check_true("인접 선언이 판정과 일치: %s-%s" % (a, b), is_adjacent(a, b))
            check_true("인접 판정은 방향이 없다: %s-%s" % (b, a), is_adjacent(b, a))
        check_true("인접하지 않은 쌍은 False", not is_adjacent("서울", "부산"))

        # 한쪽 시도를 알 수 없으면 비교하지 않는다(감정요항이 비는 것은 흔하다).
        status, reasons = reasons_of(engine, item(appraisal_summary=""))
        check("감정요항이 비면 지역 비교를 하지 않는다", status, "PASS")

        # --- 4. 가격 검증 -------------------------------------------------------
        print("\n--- 4. 가격 ---")
        status, reasons = reasons_of(engine, item(
            appraisal_price="100,000,000", minimum_bid_price="200,000,000"))
        check("최저가 > 감정가 -> FAIL", status, "FAIL")
        check_true("가격 사유에 두 값이 적힌다",
                   any(r.startswith("price_invalid") and "min=200000000" in r for r in reasons),
                   reasons)

        # 오차 허용: 정확히 tolerance만큼 크면 통과, 1원 더 크면 실패 —
        # 경계에서 방향이 뒤집히는 실수를 잡는다.
        status, _ = reasons_of(engine, item(
            appraisal_price="100,000,000",
            minimum_bid_price="{:,}".format(100_000_000 + PRICE_TOLERANCE)))
        check("오차 이내(=tolerance)는 PASS", status, "PASS")
        status, _ = reasons_of(engine, item(
            appraisal_price="100,000,000",
            minimum_bid_price="{:,}".format(100_000_000 + PRICE_TOLERANCE + 1)))
        check("오차를 1원 넘으면 FAIL", status, "FAIL")

        # 가격이 0이면(파싱 불가/미기재) 비교하지 않는다 — 누락 검사가 이미 잡는다.
        #
        # 실제 조건은 `if appraisal > 0 and minimum > 0:`라 **양쪽 모두**가 가드다.
        # 한쪽만 검증하면 반대쪽을 지웠을 때 조용히 통과한다 — 예컨대 감정가 쪽 가드를
        # 없애면 감정가 0인 물건이 전부 "최저가 > 감정가(0)"로 잡혀 대량 오탐이 된다.
        status, reasons = reasons_of(engine, item(minimum_bid_price="비공개"))
        check_true("파싱 불가 최저가는 price_invalid를 내지 않는다",
                   not any(r.startswith("price_invalid") for r in reasons), reasons)
        # 감정가가 0인 쪽(값은 있지만 0이라 누락 검사에는 걸리지 않는다).
        status, reasons = reasons_of(engine, item(
            appraisal_price="0", minimum_bid_price="9,999,999"))
        check_true("감정가가 0이면 price_invalid를 내지 않는다",
                   not any(r.startswith("price_invalid") for r in reasons), reasons)

        # parse_price 자체 계약(가격 판정의 토대).
        check("parse_price: 콤마 제거", parse_price("1,234,567"), 1234567)
        check("parse_price: 괄호 뒤는 버린다(보증금 표기)",
              parse_price("800,000,000 (80,000,000)"), 800000000)
        check("parse_price: '-'는 0", parse_price("-"), 0)
        check("parse_price: 빈 문자열은 0", parse_price(""), 0)
        check("parse_price: 숫자가 없으면 0", parse_price("비공개"), 0)

        # --- 5. 사건번호 형식 ---------------------------------------------------
        print("\n--- 5. 사건번호 형식 ---")
        for bad in ("2024다1234", "타경1234", "24타경1234", "2024타경"):
            status, reasons = reasons_of(engine, item(case_no=bad))
            check("형식 위반(%s) -> FAIL" % bad, status, "FAIL")
            check_true("형식 사유에 입력값이 적힌다",
                       any(r.startswith("case_no_format_invalid") and bad in r for r in reasons),
                       reasons)
        # 병합사건은 "2019타경10346 / 2020타경105127"처럼 여러 사건번호가 한 칸에 들어온다
        # (실데이터에 존재한다). 형식 검사는 `search()`라 부분 일치이므로 통과해야 한다 —
        # 여기서 FAIL이 나면 병합사건 전부가 "검증실패"로 표시된다.
        for good in ("2024타경1234", "2024타경1", "서울2024타경99999",
                     "2019타경10346 / 2020타경105127"):
            status, reasons = reasons_of(engine, item(case_no=good))
            check_true("정상 형식(%s)은 형식 사유가 없다" % good,
                       not any(r.startswith("case_no_format_invalid") for r in reasons), reasons)

        # --- 6. 로그 기록 실패가 검증을 죽이지 않는다 ---------------------------
        print("\n--- 6. 로그 실패 격리 ---")
        # 존재하는 파일을 디렉터리로 쓰라고 하면 열기가 실패한다.
        blocker = os.path.join(tmp, "blocker.txt")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("x")
        broken_engine = ValidationEngine(log_path=os.path.join(blocker, "validation.jsonl"))
        crashed = None
        try:
            result = broken_engine.validate(item())
        except Exception as exc:  # noqa: BLE001
            crashed, result = exc, None
        check_true("로그를 쓸 수 없어도 검증이 죽지 않는다", crashed is None, repr(crashed))
        check_true("그래도 판정 결과는 정상이다",
                   result is not None and result.validation_status == "PASS",
                   result.validation_status if result else None)

        # --- 7. 배치/요약 -------------------------------------------------------
        print("\n--- 7. 배치와 요약 ---")
        items = [item(), item(case_no=""), item()]
        validated = engine.validate_batch(items)
        check("배치는 입력 수만큼 돌려준다", len(validated), 3)
        check("배치 판정 결과", [i.validation_status for i in validated], ["PASS", "FAIL", "PASS"])
        summary = engine.summary(validated)
        check("summary total", summary["total"], 3)
        check("summary pass", summary["pass"], 2)
        check("summary fail", summary["fail"], 1)
        check("summary accuracy", summary["accuracy"], 66.7)
        check("빈 배치 summary accuracy는 0(0으로 나누지 않는다)",
              engine.summary([])["accuracy"], 0)

        # 로그가 실제로 쌓였는지(관측 경로가 살아 있는지) 확인한다.
        log_lines = 0
        with open(engine.log_path, encoding="utf-8") as fh:
            log_lines = sum(1 for _ in fh)
        check_true("검증 로그가 기록된다", log_lines > 0, log_lines)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
