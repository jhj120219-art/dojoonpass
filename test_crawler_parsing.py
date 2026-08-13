"""크롤 상세페이지 파싱 로직 회귀 테스트 (2026-08-13 Sprint 85 신설).

## 왜 지금 만드는가 — 커버리지가 지목했다

`crawler/base_crawler.py`는 **커버리지 0%**다. 이 파일에는 브라우저를 조작하는 코드와
**수집한 DOM을 데이터로 조립하는 코드**가 섞여 있는데, 후자는 브라우저 없이도 검증할 수
있는데도 한 번도 실행된 적이 없었다.

조립 로직이 이 파이프라인에서 차지하는 자리는 작지 않다.

    parse_basic_info()    상세 표를 {라벨: 값} 사전으로 만든다 -> AuctionItem의 원천
    parse_section_table() 섹션 표를 행 목록으로 만든다
    parse_gamjung()       감정평가요항표 텍스트 -> validator의 지역 대조 입력
    clean()               위 셋 전부가 쓰는 공백 정규화

`parse_gamjung()`의 결과가 곧 `ValidationEngine`의 `appraisal_summary`이고, 그것이
Sprint 78에서 BUGS #92를 드러낸 바로 그 입력이다.

## 이 테스트가 검증하는 것과 하지 않는 것

**검증한다** — DOM에서 값을 꺼낸 뒤의 **조립 규칙**: th/td 짝짓기, 중복 라벨 처리,
빈 행 걸러내기, 셀 수가 안 맞을 때, 예외가 났을 때 이미 모은 것을 지키는가.

**검증하지 않는다** — XPath가 실제 법원 페이지의 DOM과 맞는지. 그것은 살아 있는 페이지가
있어야 하고(`test_docs.py` 계열), 이 저장소는 회귀에서 실크롤을 돌리지 않는다.
**그 경계를 흐리지 않기 위해** 가짜 드라이버는 XPath를 해석하지 않고 미리 정해 둔 결과만
돌려준다 — "XPath가 맞다"고 착각하게 만드는 검사를 만들지 않는다.

    python test_crawler_parsing.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler.base_crawler import (
    clean, parse_basic_info, parse_section_table, parse_gamjung,
)

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    ok = bool(cond)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("" if ok else " -> " + str(detail))))
    if not ok:
        failures.append(name)


# ---------------------------------------------------------------------------
# 가짜 드라이버 — selenium API 중 이 함수들이 실제로 쓰는 것만 흉내 낸다.
#
# 일부러 최소한만 구현한다. 더 그럴듯하게 만들수록 "selenium을 다시 구현한 것"을
# 검증하게 되고, 정작 제품 로직은 덜 보게 된다.
# ---------------------------------------------------------------------------
class FakeElement:
    def __init__(self, text="", ths=None, tds=None, raises=None):
        self._text = text
        self._ths = ths or []
        self._tds = tds or []
        self._raises = raises

    @property
    def text(self):
        if self._raises:
            raise self._raises
        return self._text

    def find_elements(self, by, value):
        # base_crawler는 행에서 TAG_NAME으로 th/td만 찾는다.
        v = str(value).lower()
        if v == "th":
            return self._ths
        if v == "td":
            return self._tds
        return []


class FakeDriver:
    """find_elements/find_element의 결과를 **미리 정해 둔 값**으로 돌려준다.

    XPath는 해석하지 않는다(위 docstring 참고). 예외를 주입할 수도 있다.
    """

    def __init__(self, elements=None, single=None, raises=None):
        self._elements = elements if elements is not None else []
        self._single = single
        self._raises = raises

    def find_elements(self, by, value):
        if self._raises:
            raise self._raises
        return self._elements

    def find_element(self, by, value):
        if self._raises:
            raise self._raises
        if self._single is None:
            raise RuntimeError("no such element")
        return self._single


def row(ths=(), tds=()):
    return FakeElement(ths=[FakeElement(t) for t in ths],
                       tds=[FakeElement(t) for t in tds])


# ---------------------------------------------------------------------------
def test_clean():
    print("\n--- 1. clean(): 공백 정규화 ---")
    check("연속 공백을 하나로", clean("서울특별시    강남구"), "서울특별시 강남구")
    check("탭/줄바꿈도 공백으로", clean("서울\t강남\n역삼"), "서울 강남 역삼")
    check("앞뒤 공백 제거", clean("   값   "), "값")
    check("줄바꿈만 있는 값은 빈 문자열", clean("\n\n  \t "), "")
    check("빈 문자열", clean(""), "")
    # 크롤 원문에는 비단절 공백(NBSP)이 흔하다. `\s`가 이를 포함하는지 명시적으로 고정한다 —
    # 포함하지 않으면 "서울<NBSP>강남"이 그대로 남아 주소 정규화가 어긋난다.
    #
    # ★ NBSP를 **소스 리터럴로 쓰지 않고** chr()로 만든다. U+00A0은 cp949에 없어서
    #   `test_console_encoding.py`의 가드(테스트 파일의 모든 문자열 리터럴은 cp949로
    #   내보낼 수 있어야 한다)에 걸린다. 여기서는 그 문자가 **검사 대상 데이터**라
    #   예외를 만드는 대신 런타임에 조립해 가드의 엄격함을 그대로 둔다.
    #   (되돌려 리터럴로 바꾸면 전체 회귀가 그 가드에서 실패한다 — 의도된 동작이다)
    nbsp = chr(0xA0)
    check("비단절 공백(NBSP)도 정규화된다", clean("서울" + nbsp + "특별시"), "서울 특별시")
    fullwidth = chr(0x3000)   # 전각 공백은 cp949에 있지만 대칭을 위해 같은 방식으로 쓴다
    check("전각 공백도 정규화된다", clean("서울" + fullwidth + "특별시"), "서울 특별시")


def test_parse_basic_info():
    print("\n--- 2. parse_basic_info(): 상세 표 -> 사전 ---")

    # 기본: th와 td를 순서대로 짝짓는다.
    d = FakeDriver([
        row(ths=["사건번호", "물건번호"], tds=["2024타경1234", "1"]),
        row(ths=["소재지"], tds=["서울특별시 강남구 역삼동 736-1"]),
    ])
    check("th/td를 순서대로 짝짓는다", parse_basic_info(d),
          {"사건번호": "2024타경1234", "물건번호": "1",
           "소재지": "서울특별시 강남구 역삼동 736-1"})

    # 값에 붙은 공백은 clean으로 정리된다.
    d = FakeDriver([row(ths=["  소재지  "], tds=["서울특별시    강남구"])])
    check("키와 값 모두 clean된다", parse_basic_info(d), {"소재지": "서울특별시 강남구"})

    # ★ 같은 라벨이 여러 번 나오면 **먼저 나온 것이 이긴다**(`key not in result`).
    #   법원 상세페이지는 요약표와 상세표에 같은 라벨을 반복해서 쓴다. 뒤가 이기면
    #   요약값이 상세값을 덮어써 조용히 다른 데이터가 저장된다.
    d = FakeDriver([
        row(ths=["소재지"], tds=["첫 번째 값"]),
        row(ths=["소재지"], tds=["두 번째 값"]),
    ])
    check("중복 라벨은 첫 번째가 이긴다", parse_basic_info(d), {"소재지": "첫 번째 값"})

    # td가 부족하면 "-"로 채운다(값이 아예 빠지는 것보다 낫다는 현재 판단).
    d = FakeDriver([row(ths=["사건번호", "비고"], tds=["2024타경1"])])
    check("td가 모자라면 '-'", parse_basic_info(d), {"사건번호": "2024타경1", "비고": "-"})

    # 빈 키나 빈 값은 넣지 않는다 — 빈 키가 들어가면 사전이 오염된다.
    d = FakeDriver([
        row(ths=["", "소재지"], tds=["버려질 값", "서울"]),
        row(ths=["빈값라벨"], tds=[""]),
    ])
    check("빈 키/빈 값은 넣지 않는다", parse_basic_info(d), {"소재지": "서울"})

    # th가 없는 행(값만 있는 행)은 무시된다.
    check("th 없는 행은 무시", parse_basic_info(FakeDriver([row(tds=["값만"])])), {})

    # 표가 아예 없으면 빈 사전(예외가 아니라).
    check("표가 없으면 빈 사전", parse_basic_info(FakeDriver([])), {})

    # ★ 중간에 예외가 나도 **이미 모은 것은 지킨다.**
    #   한 셀의 텍스트를 읽다 StaleElementReference가 나는 일은 실제로 흔하다.
    #   여기서 전부 버리면 그 물건은 필수 필드 누락으로 FAIL 처리된다.
    boom = FakeElement(raises=RuntimeError("stale element"))
    d = FakeDriver([
        row(ths=["사건번호"], tds=["2024타경1"]),
        FakeElement(ths=[boom], tds=[FakeElement("x")]),
    ])
    check("중간 예외 시 앞서 모은 값은 남는다", parse_basic_info(d), {"사건번호": "2024타경1"})

    # 드라이버 자체가 터져도 예외를 던지지 않는다(호출부가 방어하지 않는다).
    check("드라이버 예외도 삼키고 빈 사전",
          parse_basic_info(FakeDriver(raises=RuntimeError("driver dead"))), {})


def test_parse_section_table():
    print("\n--- 3. parse_section_table(): 섹션 표 -> 행 목록 ---")

    d = FakeDriver([
        row(tds=["1", "홍길동", "전부"]),
        row(tds=["2", "김철수", "일부"]),
    ])
    check("td 행을 순서대로 모은다", parse_section_table(d, "임차인"),
          [["1", "홍길동", "전부"], ["2", "김철수", "일부"]])

    # 헤더 행(td 없음)은 건너뛴다.
    d = FakeDriver([row(ths=["번호", "이름"]), row(tds=["1", "홍길동"])])
    check("td 없는 헤더 행은 건너뛴다", parse_section_table(d, "임차인"), [["1", "홍길동"]])

    # ── 변이 시험에서 확인한 사실 (2026-08-13 Sprint 85) ───────────────────
    # `parse_section_table()`에는 행을 거르는 가드가 **두 개** 있다.
    #
    #     if not cells:      continue      # (A) td가 아예 없는 행
    #     if any(texts):     records.append # (B) 모든 셀이 빈 행
    #
    # (A)를 제거하는 변이를 넣었더니 **어떤 검사도 실패하지 않았다.** 이유는
    # cells가 비면 texts도 빈 리스트가 되고 `any([])`가 False라 (B)가 같은 행을
    # 다시 걸러내기 때문이다. 즉 **(A)는 출력에 영향을 주지 않는 순수 중복**이고,
    # 리스트 컴프리헨션 한 번을 아끼는 미세 최적화일 뿐이다.
    #
    # 동작으로는 구분할 수 없으므로 억지로 검사를 만들지 않았고, 코드도 건드리지
    # 않았다(무해하고 의도를 드러내는 방어라 지울 이유가 없다).
    # 이 주석은 다음 사람이 같은 변이를 넣고 "테스트가 약하다"고 오판하는 것을 막는다.

    # 셀이 전부 빈 행은 버린다 — 표 하단의 빈 줄이 데이터로 들어가면 안 된다.
    d = FakeDriver([row(tds=["", "  ", "\n"]), row(tds=["1", "홍길동"])])
    check("모든 셀이 빈 행은 버린다", parse_section_table(d, "임차인"), [["1", "홍길동"]])

    # 일부만 빈 행은 **남긴다**(빈 칸도 의미가 있는 표가 있다).
    d = FakeDriver([row(tds=["1", "", "전부"])])
    check("일부만 빈 행은 남긴다", parse_section_table(d, "임차인"), [["1", "", "전부"]])

    check("표가 없으면 빈 목록", parse_section_table(FakeDriver([]), "임차인"), [])
    check("드라이버 예외도 삼키고 빈 목록",
          parse_section_table(FakeDriver(raises=RuntimeError("boom")), "임차인"), [])

    # 예외가 나도 앞서 모은 행은 지킨다.
    boom_row = FakeElement(tds=[FakeElement(raises=RuntimeError("stale"))])
    d = FakeDriver([row(tds=["1", "홍길동"]), boom_row])
    check("중간 예외 시 앞서 모은 행은 남는다",
          parse_section_table(d, "임차인"), [["1", "홍길동"]])


def test_parse_gamjung():
    print("\n--- 4. parse_gamjung(): 감정평가요항표 텍스트 ---")
    # 이 반환값이 곧 ValidationEngine의 appraisal_summary이고,
    # validator의 지역 대조(address_mismatch) 입력이다.
    d = FakeDriver(single=FakeElement("서울특별시   강남구\n역삼동 일대"))
    check("텍스트를 clean해서 돌려준다", parse_gamjung(d), "서울특별시 강남구 역삼동 일대")

    # 요소를 못 찾으면 **빈 문자열**이다(None이 아니라).
    # validator는 `if addr_sido and appraisal_sido`로 양쪽이 있을 때만 비교하므로,
    # 빈 문자열이면 지역 대조를 아예 건너뛴다 — 모른다고 FAIL을 붙이지 않는 설계다.
    check("요소가 없으면 빈 문자열", parse_gamjung(FakeDriver()), "")
    check("드라이버 예외도 빈 문자열",
          parse_gamjung(FakeDriver(raises=RuntimeError("boom"))), "")
    check("텍스트 읽기 실패도 빈 문자열",
          parse_gamjung(FakeDriver(single=FakeElement(raises=RuntimeError("stale")))), "")

    # 빈 요약은 validator에서 "지역 비교 안 함"으로 이어져야 한다 — 그 연결을 직접 확인한다.
    from validator.validation_engine import ValidationEngine
    from models.auction_item import AuctionItem
    import tempfile
    log = os.path.join(tempfile.mkdtemp(prefix="qa_parse_"), "v.jsonl")
    engine = ValidationEngine(log_path=log)
    item = AuctionItem(
        case_no="2024타경1", item_no="1", address="서울특별시 강남구 역삼동",
        property_type="아파트", appraisal_price="100000000", minimum_bid_price="80000000",
        auction_date="2026-09-01", status="진행", court_code="B000210",
        court_name="서울중앙지방법원",
        appraisal_summary=parse_gamjung(FakeDriver()),   # <- 빈 문자열
        crawl_date="2026-08-13",
    )
    engine.validate(item)
    check_true("빈 요약이면 address_mismatch가 붙지 않는다",
               not any(r.startswith("address_mismatch") for r in item.validation_reasons),
               item.validation_reasons)


def run():
    test_clean()
    test_parse_basic_info()
    test_parse_section_table()
    test_parse_gamjung()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
