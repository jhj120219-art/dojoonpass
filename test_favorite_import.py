"""마이리스트 가져오기 회귀 테스트 (2026-08-28 신설).

    python test_favorite_import.py

## 무엇을 검증하는가

    1. 파서      순수 함수. 정상/빈/기형/중복/병합 사건/CSV·TSV·자유형
    2. 매칭      후보 좁히기 규칙과 **모호할 때 고르지 않는다**는 계약
    3. API       미리보기 -> 커밋 -> 조회 전 구간(실제 라우터 함수 호출)
    4. 격리      다른 사용자의 메모/관심물건이 섞이지 않는다
    5. 멱등      같은 입력을 두 번 커밋해도 결과가 같고 메모가 지워지지 않는다
    6. 계약      `crawler/resume.py` 의 사건번호 규칙과 갈리지 않는다

## 운영 DB 를 건드리지 않는다

`test_subscription_policy.py` 와 **같은 방식**이다 - `storage.database.DB_PATH` 를
임시 스냅샷으로 갈아끼운 뒤에야 제품 모듈을 import 한다. `get_connection()` 이
호출 시점에 모듈 전역을 읽으므로 이 한 줄이 라우터까지 함께 옮긴다.
`run_python_tests.py` 가 파일마다 운영 DB 지문을 재서 이 약속을 감시한다.

출력은 ASCII 만 쓴다(콘솔 cp949).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import atexit as _qa_atexit
import shutil as _qa_shutil
import tempfile as _qa_tempfile
import storage.database as _qa_dbmod
_qa_tmp = _qa_tempfile.mkdtemp(prefix="dojoonpass-qa-")
_qa_atexit.register(_qa_shutil.rmtree, _qa_tmp, True)
_qa_scratch = os.path.join(_qa_tmp, "auction.db")
if os.path.exists(_qa_dbmod.DB_PATH):
    _qa_dbmod.snapshot_live_db(_qa_scratch)
_qa_dbmod.DB_PATH = _qa_scratch

from storage.database import get_connection
from normalizer.mylist_import import (
    STATUS_ALREADY, STATUS_AMBIGUOUS, STATUS_DUPLICATE_INPUT, STATUS_MATCHED,
    STATUS_NOT_FOUND, STATUS_NO_CASE_NO,
    case_no_matches, dedupe_key, normalize_case_no, normalize_tags,
    parse_mylist_text, resolve_row,
)
import api.v1.favorite_import as imp
from api.v1.favorites import get_favorites

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def rows_of(text):
    return parse_mylist_text(text)["rows"]


# ---------------------------------------------------------------------------
# 1. 사건번호 정규화 / 매칭 규칙
# ---------------------------------------------------------------------------
def test_case_no():
    print("\n--- 1. case_no ---")
    check("공백이 낀 표기를 표준으로", normalize_case_no("2024 타경 1009"), "2024타경1009")
    check("붙여 쓴 표기", normalize_case_no("2024타경1009"), "2024타경1009")
    check("병합 사건은 원본 순서로 잇는다",
          normalize_case_no("2008타경25092 / 2015타경19958"),
          "2008타경25092 / 2015타경19958")
    check("같은 값이 두 번 나오면 한 번만",
          normalize_case_no("2024타경1 2024타경1"), "2024타경1")
    check("사건번호가 없으면 빈 문자열", normalize_case_no("서울중앙지방법원"), "")
    check("None 도 빈 문자열", normalize_case_no(None), "")
    check("타경이 아닌 사건부호는 받지 않는다", normalize_case_no("2024타채1009"), "")

    # 접두 부분문자열 오검출 - crawler/resume.py 가 고쳤던 바로 그 결함.
    check("접두 부분문자열은 같은 물건이 아니다",
          case_no_matches("2024타경1009", "2024타경100920"), False)
    check("구성요소를 공유하면 같은 물건",
          case_no_matches("2023타경300780", "2023타경300780 / 2023타경302427"), True)
    check("병합 대 병합(순서 무관)",
          case_no_matches("2023타경302427 / 2023타경300780",
                          "2023타경300780 / 2023타경302427"), True)
    check("빈 값은 아무것도 일치시키지 않는다", case_no_matches("", ""), False)

    # 크롤러 쪽 구현과 규칙이 갈리지 않는지 **나란히 태워** 본다.
    # (두 함수는 의존 방향 때문에 일부러 따로 있다 - mylist_import.py 주석 참고)
    from crawler.resume import case_no_matches_list_entry
    pairs = [
        ("2024타경1009", "2024타경100920"),
        ("2023타경300780", "2023타경300780 / 2023타경302427"),
        ("2023타경302427 / 2023타경300780", "2023타경300780 / 2023타경302427"),
        ("", ""),
        ("2024타경1", "2024타경1"),
        ("2024타경1", ""),
    ]
    same = all(case_no_matches(a, b) == case_no_matches_list_entry(a, b) for a, b in pairs)
    check("crawler/resume.py 와 판정이 같다", same, True)


# ---------------------------------------------------------------------------
# 2. 파서 - 세 갈래 입력
# ---------------------------------------------------------------------------
def test_parser():
    print("\n--- 2. parser ---")
    check("빈 입력은 0행", rows_of(""), [])
    check("None 입력도 0행", parse_mylist_text(None)["rows"], [])
    check("공백/개행만 있어도 0행", rows_of("\n\n   \n\t\n"), [])

    free = rows_of("서울중앙지방법원 2024 타경 1009 물건번호 3 #관심 #급매")
    check("자유형 1행", len(free), 1)
    check("자유형 case_no", free[0]["case_no"], "2024타경1009")
    check("자유형 item_no", free[0]["item_no"], "3")
    check("자유형 court_name", free[0]["court_name"], "서울중앙지방법원")
    check("자유형 tags", free[0]["tags"], ["관심", "급매"])

    attached = rows_of("2024타경1009-7 서울중앙지방법원")
    check("붙여 쓴 -N 은 물건번호", attached[0]["item_no"], "7")
    check("붙여 쓴 -N 은 사건번호에서 빠진다", attached[0]["case_no"], "2024타경1009")

    spaced = rows_of("2024타경1009 - 7")
    check("공백이 낀 - N 은 물건번호로 읽지 않는다", spaced[0]["item_no"], None)

    # 우리 내보내기(src/lib/exportList.ts)를 그대로 되붙이기.
    csv = (
        "법원,사건번호,물건번호,물건종류,소재지,감정가,최저입찰가,매각기일,상태,유찰횟수\n"
        "서울중앙지방법원,2024타경1009,3,\"상가,오피스텔,근린시설\",서울 강남구 역삼동 1,"
        "2813645810,1800000000,2026-09-01,신건,0\n"
    )
    parsed = parse_mylist_text(csv)
    check("헤더를 인식한다", parsed["header_detected"], True)
    check("헤더 줄은 데이터가 아니다", len(parsed["rows"]), 1)
    row = parsed["rows"][0]
    check("열 매핑 case_no", row["case_no"], "2024타경1009")
    check("열 매핑 item_no", row["item_no"], "3")
    check("열 매핑 court_name", row["court_name"], "서울중앙지방법원")
    # 따옴표 안의 쉼표 때문에 열이 밀리면 소재지 칸에 물건종류가 들어온다.
    check("따옴표 안 쉼표에 열이 밀리지 않는다", row["address"], "서울 강남구 역삼동 1")

    tsv = "법원\t사건번호\t물건번호\t메모\t태그\n안산지원\t2024타경2\t1\t현장확인함\t단독,급매\n"
    trow = parse_mylist_text(tsv)["rows"][0]
    check("TSV court_name", trow["court_name"], "안산지원")
    check("TSV memo", trow["memo"], "현장확인함")
    check("TSV tags(# 없이 쉼표 나열)", trow["tags"], ["단독", "급매"])

    # 헤더처럼 보이는 데이터 줄
    looks = parse_mylist_text("사건번호 2024타경1009\n")
    check("값이 든 줄은 헤더가 아니다", looks["header_detected"], False)
    check("값이 든 줄은 데이터로 남는다", len(looks["rows"]), 1)

    junk = rows_of("여기에는 사건번호가 없습니다\n@@@!!!\n")
    check("사건번호 없는 줄도 버리지 않는다", len(junk), 2)
    check("사건번호 없는 줄의 case_no 는 빈 값", junk[0]["case_no"], "")

    numbered = rows_of("\n\n2024타경1\n")
    check("빈 줄을 건너뛰어도 line_no 는 원문 기준", numbered[0]["line_no"], 3)

    big = parse_mylist_text("\n".join("2024타경%d" % i for i in range(1, 700)))
    check("상한을 넘으면 잘라내되 사실을 알린다", big["truncated"], True)
    check("상한까지만 읽는다", len(big["rows"]), 500)

    check("태그 정규화(중복/# 제거)", normalize_tags(["#a", "a", " b ", ""]), "a,b")
    check("태그 문자열도 받는다", normalize_tags("a, b"), "a,b")
    check("태그 None", normalize_tags(None), "")


# ---------------------------------------------------------------------------
# 3. 매칭 - 좁히기 규칙과 "고르지 않는다"는 계약
# ---------------------------------------------------------------------------
def cand(i, case_no, item_no=None, court=None, addr=None):
    return {"id": i, "case_no": case_no, "item_no": item_no,
            "court_name": court, "full_address": addr}


def test_resolve():
    print("\n--- 3. resolve ---")
    parsed = rows_of("2024타경1")[0]
    check("후보 0건이면 NOT_FOUND",
          resolve_row(parsed, [])["status"], STATUS_NOT_FOUND)
    check("사건번호를 못 읽으면 NO_CASE_NO",
          resolve_row(rows_of("주소만 있음")[0], [])["status"], STATUS_NO_CASE_NO)

    one = resolve_row(parsed, [cand(10, "2024타경1", "1")])
    check("후보 1건이면 MATCHED", one["status"], STATUS_MATCHED)
    check("MATCHED 의 item_id", one["item_id"], 10)

    many = [cand(10, "2024타경1", "1"), cand(11, "2024타경1", "2")]
    amb = resolve_row(parsed, many)
    check("물건번호가 없고 후보가 여럿이면 AMBIGUOUS", amb["status"], STATUS_AMBIGUOUS)
    check("후보를 임의로 고르지 않는다", amb["item_id"], None)
    check("후보를 전부 돌려준다", sorted(amb["candidate_ids"]), [10, 11])

    with_item = resolve_row(rows_of("2024타경1 물건번호 2")[0], many)
    check("물건번호가 후보를 좁힌다", with_item["item_id"], 11)
    check("무엇으로 좁혔는지 알린다", with_item["narrowed_by"], ["item_no"])

    # 물건번호가 어긋나면 0건으로 만들지 않고 되돌린다(표기 차이일 수 있다).
    mismatched = resolve_row(rows_of("2024타경1 물건번호 9")[0], many)
    check("물건번호 불일치는 후보를 지우지 않는다", mismatched["status"], STATUS_AMBIGUOUS)

    courts = [cand(10, "2024타경1", "1", "서울중앙지방법원"),
              cand(11, "2024타경1", "2", "안산지원")]
    by_court = resolve_row(rows_of("안산지원 2024타경1")[0], courts)
    check("법원명이 후보를 좁힌다", by_court["item_id"], 11)

    # 법원 표기가 우리와 다르면(코드 등) 좁히기를 되돌린다 - "없음"이라고 말하지 않는다.
    unknown_court = resolve_row(
        {"case_no": "2024타경1", "item_no": None,
         "court_name": "제1법원", "address": None}, courts)
    check("모르는 법원 표기로 0건을 만들지 않는다",
          unknown_court["status"], STATUS_AMBIGUOUS)

    addrs = [cand(10, "2024타경1", "1", None, "서울 강남구 역삼동 1"),
             cand(11, "2024타경1", "2", None, "부산 해운대구 우동 2")]
    by_addr = resolve_row(
        {"case_no": "2024타경1", "item_no": None,
         "court_name": None, "address": "해운대구 우동"}, addrs)
    check("주소 힌트가 후보를 좁힌다", by_addr["item_id"], 11)

    # 병합 사건: 붙여넣은 쪽이 단일, DB 가 병합.
    merged = resolve_row(rows_of("2015타경19958")[0],
                         [cand(20, "2008타경25092 / 2015타경19958", "1")])
    check("DB 의 병합 사건과 맞는다", merged["item_id"], 20)

    check("중복 키는 순서를 타지 않는다",
          dedupe_key({"case_no": "A / B", "item_no": "1"}) ==
          dedupe_key({"case_no": "B / A", "item_no": "1"}), True)
    check("사건번호 없는 줄은 중복 판정에서 제외",
          dedupe_key({"case_no": "", "item_no": None}), None)


# ---------------------------------------------------------------------------
# 4~6. API 전 구간 (실제 라우터 함수 호출)
# ---------------------------------------------------------------------------
USER_A = "qa-import-user-a"
USER_B = "qa-import-user-b"
SEED_CASE = "9999타경70001"
SEED_MERGED = "9999타경70003 / 9999타경70004"


def seed(conn):
    """검사용 물건 3건. 스크래치 DB 라 지우지 않아도 남지 않는다."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorite_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            item_id INTEGER NOT NULL REFERENCES auction_item(id),
            memo TEXT, tags TEXT, source TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(user_id, item_id))
    """)
    ids = {}
    for key, case_no, item_no, court, addr in [
        ("a", SEED_CASE, "1", "서울중앙지방법원", "서울 강남구 역삼동 1"),
        ("b", SEED_CASE, "2", "서울중앙지방법원", "서울 강남구 역삼동 2"),
        ("m", SEED_MERGED, "1", "안산지원", "경기 안산시 단원구 3"),
    ]:
        cur = conn.execute(
            "INSERT INTO auction_item (case_no, item_no, court_name, full_address) "
            "VALUES (?,?,?,?)", (case_no, item_no, court, addr))
        ids[key] = cur.lastrowid
    conn.commit()
    return ids


class Req:
    """pydantic 모델 대신 쓰는 최소 대역. 라우터는 속성만 읽는다."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_api(ids):
    print("\n--- 4. API preview ---")
    text = "\n".join([
        "%s 물건번호 1 #관심" % SEED_CASE,     # MATCHED
        "%s" % SEED_CASE,                      # AMBIGUOUS (물건 2건)
        "9999타경70004",                       # 병합 사건의 한쪽 -> MATCHED
        "9999타경99999",                       # NOT_FOUND
        "사건번호가 없는 줄",                   # NO_CASE_NO
        "%s 물건번호 1" % SEED_CASE,           # DUPLICATE_IN_INPUT (1행과 같은 키)
    ])
    res = imp.preview_import(Req(text=text, source="내 목록"), user_id=USER_A)
    check("preview 성공", res["success"], True)
    rows = res["data"]["rows"]
    check("preview 행 수", len(rows), 6)
    check("1행 MATCHED", rows[0]["status"], STATUS_MATCHED)
    check("1행이 고른 물건", rows[0]["item_id"], ids["a"])
    check("1행 태그가 살아 있다", rows[0]["tags"], ["관심"])
    check("2행 AMBIGUOUS", rows[1]["status"], STATUS_AMBIGUOUS)
    check("2행 후보 2건", len(rows[1]["candidates"]), 2)
    check("3행 병합 사건 매칭", rows[2]["item_id"], ids["m"])
    check("4행 NOT_FOUND", rows[3]["status"], STATUS_NOT_FOUND)
    check("4행 원문을 버리지 않는다", rows[3]["raw"], "9999타경99999")
    check("5행 NO_CASE_NO", rows[4]["status"], STATUS_NO_CASE_NO)
    check("6행 DUPLICATE_IN_INPUT", rows[5]["status"], STATUS_DUPLICATE_INPUT)
    check("요약 total", res["data"]["summary"]["total"], 6)
    check("요약은 0인 상태도 키를 남긴다",
          STATUS_ALREADY in res["data"]["summary"], True)
    check("메모 기능 사용 가능", res["data"]["notes_enabled"], True)

    print("\n--- 4b. preview 는 아무것도 저장하지 않는다 ---")
    conn = get_connection()
    try:
        n = conn.execute("SELECT COUNT(*) FROM favorites WHERE user_id=?",
                         (USER_A,)).fetchone()[0]
    finally:
        conn.close()
    check("preview 후 관심물건 0건", n, 0)

    print("\n--- 5. commit ---")
    commit = imp.commit_import(Req(rows=[
        Req(item_id=ids["a"], memo="현장 확인함", tags=["관심"], source="내 목록"),
        # 메모/태그/출처가 **전부** 비어 있으면 메모 행을 만들지 않는다.
        # (출처만 있어도 만든다 - 어디서 가져온 목록인지는 그 자체로 정보다)
        Req(item_id=ids["m"], memo=None, tags=None, source=None),
        Req(item_id=10 ** 19, memo=None, tags=None, source=None),   # 범위 밖 id
        Req(item_id=987654321, memo=None, tags=None, source=None),  # 없는 물건
    ]), user_id=USER_A)
    check("commit 성공", commit["success"], True)
    check("2건 추가", commit["data"]["summary"]["added"], 2)
    check("2건 실패(부분 성공)", commit["data"]["summary"]["failed"], 2)
    check("범위 밖 id 는 500 이 아니라 NOT_FOUND",
          commit["data"]["results"][2]["status"], STATUS_NOT_FOUND)
    check("없는 물건도 NOT_FOUND", commit["data"]["results"][3]["status"], STATUS_NOT_FOUND)
    check("메모가 실제로 쓰였다", commit["data"]["results"][0]["note_written"], True)
    check("전부 비면 메모 행을 만들지 않는다",
          commit["data"]["results"][1]["note_written"], False)
    # 출처만 있는 경우는 쓴다 - 위 규칙의 반대편을 함께 고정해 둔다.
    source_only = imp.commit_import(Req(rows=[
        Req(item_id=ids["m"], memo=None, tags=None, source="내 목록")]),
        user_id=USER_A)
    check("출처만 있어도 메모 행을 만든다",
          source_only["data"]["results"][0]["note_written"], True)

    print("\n--- 6. 조회 ---")
    listed = get_favorites(user_id=USER_A)
    check("조회 성공", listed["success"], True)
    items = {i["id"]: i for i in listed["data"]}
    check("담은 2건이 보인다", sorted(items), sorted([ids["a"], ids["m"]]))
    check("메모가 함께 나온다", items[ids["a"]]["memo"], "현장 확인함")
    check("태그가 배열로 나온다", items[ids["a"]]["tags"], ["관심"])
    check("메모 없는 물건은 빈 문자열(null 아님)", items[ids["m"]]["memo"], "")
    check("기존 필드가 그대로 있다", items[ids["a"]]["case_no"], SEED_CASE)

    print("\n--- 7. 재실행(멱등) ---")
    again = imp.commit_import(Req(rows=[
        Req(item_id=ids["a"], memo=None, tags=None, source=None),
    ]), user_id=USER_A)
    check("두 번째 커밋은 ALREADY", again["data"]["results"][0]["status"], STATUS_ALREADY)
    check("추가 0건", again["data"]["summary"]["added"], 0)
    listed2 = get_favorites(user_id=USER_A)
    check("재실행 후에도 2건", len(listed2["data"]), 2)
    memo_after = {i["id"]: i for i in listed2["data"]}[ids["a"]]["memo"]
    check("빈 메모로 기존 메모를 지우지 않는다", memo_after, "현장 확인함")

    # ★ 위 검사는 **UPSERT 에 닿지도 않는다** - 셋 다 비면 _upsert_note 가 일찍
    #   돌아가기 때문이다(변이가 생존했다). 실제로 UPSERT 를 타면서 memo 만 비어 있는
    #   경우 - 출처만 채워 다시 가져오는 흔한 상황 - 를 따로 확인한다.
    imp.commit_import(Req(rows=[
        Req(item_id=ids["a"], memo="", tags=None, source="다시 가져옴")]),
        user_id=USER_A)
    kept = {i["id"]: i for i in get_favorites(user_id=USER_A)["data"]}[ids["a"]]
    check("★ 출처만 갱신해도 기존 메모는 남는다", kept["memo"], "현장 확인함")
    check("★ 출처만 갱신해도 기존 태그는 남는다", kept["tags"], ["관심"])

    preview2 = imp.preview_import(Req(text="%s 물건번호 1" % SEED_CASE, source=None),
                                  user_id=USER_A)
    check("이미 담은 것은 ALREADY_FAVORITED",
          preview2["data"]["rows"][0]["status"], STATUS_ALREADY)

    print("\n--- 8. 사용자 격리 ---")
    listed_b = get_favorites(user_id=USER_B)
    check("다른 사용자에게는 0건", listed_b["data"], [])
    imp.commit_import(Req(rows=[
        Req(item_id=ids["a"], memo="B 의 메모", tags=None, source=None)]),
        user_id=USER_B)
    b_items = {i["id"]: i for i in get_favorites(user_id=USER_B)["data"]}
    a_items = {i["id"]: i for i in get_favorites(user_id=USER_A)["data"]}
    check("B 의 메모는 B 에게만", b_items[ids["a"]]["memo"], "B 의 메모")
    check("A 의 메모는 바뀌지 않는다", a_items[ids["a"]]["memo"], "현장 확인함")

    print("\n--- 9. 메모 편집(PUT) ---")
    put = imp.put_note(ids["a"], Req(memo="다시 씀", tags=["급매"], source="내 목록"),
                       user_id=USER_A)
    check("PUT 성공", put["success"], True)
    check("PUT 은 통째로 교체한다", put["data"]["tags"], "급매")
    cleared = imp.put_note(ids["a"], Req(memo="", tags=[], source=""), user_id=USER_A)
    check("PUT 은 빈 값으로 지울 수 있다", cleared["data"]["memo"], "")
    not_mine = imp.put_note(ids["b"], Req(memo="x", tags=None, source=None),
                            user_id=USER_A)
    check("담지 않은 물건에는 메모를 쓸 수 없다", not_mine["success"], False)
    # ★ 위 검사만으로는 부족하다 - 그 물건을 **아무도** 담지 않았으면 소유권 조건을
    #   빼도 똑같이 거절된다(변이가 생존했다). 다른 사용자가 담은 물건으로 확인한다.
    imp.commit_import(Req(rows=[
        Req(item_id=ids["b"], memo=None, tags=None, source=None)]), user_id=USER_B)
    others = imp.put_note(ids["b"], Req(memo="침범", tags=None, source=None),
                          user_id=USER_A)
    check("★ 다른 사용자가 담은 물건에도 메모를 쓸 수 없다", others["success"], False)
    check("사유는 '내 관심물건이 아니다'", others["error"], "FAVORITE_NOT_FOUND")
    bad_id = imp.put_note(10 ** 19, Req(memo="x", tags=None, source=None),
                          user_id=USER_A)
    check("범위 밖 id 는 500 이 아니다", bad_id["success"], False)

    print("\n--- 10. 커밋 입력 검증 ---")
    empty = imp.commit_import(Req(rows=[]), user_id=USER_A)
    check("빈 커밋은 거절", empty["error"], "FAVORITE_IMPORT_EMPTY")
    too_many = imp.commit_import(
        Req(rows=[Req(item_id=ids["a"], memo=None, tags=None, source=None)]
                 * (imp.MAX_COMMIT_ROWS + 1)), user_id=USER_A)
    check("상한 초과는 거절", too_many["error"], "FAVORITE_IMPORT_TOO_LARGE")

    empty_preview = imp.preview_import(Req(text="", source=None), user_id=USER_A)
    check("빈 텍스트 미리보기는 성공하되 0행", empty_preview["data"]["rows"], [])
    check("빈 텍스트는 사유를 알린다",
          empty_preview["message"], "가져올 내용을 찾지 못했습니다")


def test_notes_absent(ids):
    """migration 026 이 없는 환경에서도 죽지 않는가 (운영 적용은 승인 영역)."""
    print("\n--- 11. favorite_notes 가 없는 환경 ---")
    conn = get_connection()
    try:
        conn.execute("DROP TABLE IF EXISTS favorite_notes")
        conn.commit()
    finally:
        conn.close()

    listed = get_favorites(user_id=USER_A)
    check("관심물건 조회가 500 이 되지 않는다", listed["success"], True)
    check("메모는 빈 값으로 떨어진다", listed["data"][0]["memo"], "")

    prev = imp.preview_import(Req(text=SEED_CASE, source=None), user_id=USER_A)
    check("미리보기는 그대로 동작한다", prev["success"], True)
    check("메모 기능이 꺼졌다고 알린다", prev["data"]["notes_enabled"], False)

    committed = imp.commit_import(Req(rows=[
        Req(item_id=ids["b"], memo="쓰이지 않는다", tags=None, source=None)]),
        user_id=USER_A)
    check("담기는 여전히 된다", committed["data"]["summary"]["added"], 1)
    check("메모가 안 쓰였다고 정직하게 알린다",
          committed["data"]["results"][0]["note_written"], False)

    put = imp.put_note(ids["b"], Req(memo="x", tags=None, source=None), user_id=USER_A)
    check("메모 편집은 조용히 성공하지 않는다", put["success"], False)
    check("사유 코드를 준다", put["error"], "FAVORITE_NOTE_UNAVAILABLE")


# ---------------------------------------------------------------------------
# 14. HTTP 층 (TestClient) — 함수 직접 호출이 **못 보는 것**을 본다
#
# 위 4~10번은 라우터 함수를 직접 불렀다. 그래서 다음 층이 전혀 검증되지 않았다:
#
#     pydantic 요청 검증   (`item_id: "abc"` 가 422 인가, `text` 누락이 422 인가)
#     인증 의존성          (토큰 없음/틀림이 401 인가)
#     JSON 직렬화          (한국어 원문·태그 배열이 그대로 왕복하는가)
#
# 실제로 이 층을 처음 태웠을 때 **가짜 결함 하나를 만들어 냈다** — 사본이 운영과 같은
# 마이그레이션 020 상태라 `favorite_notes` 가 없었고, 메모가 안 남는 것이 결함처럼
# 보였다. 그래서 이 파일은 스크래치에 테이블을 직접 만들어 두고(`seed()`),
# 11번이 **없는 경우**를 따로 검증한다. 두 상태를 섞지 않는 것이 요점이다.
# ---------------------------------------------------------------------------
def test_http_layer(ids):
    print("\n--- 14. HTTP 층 (TestClient) ---")
    from fastapi.testclient import TestClient
    from jose import jwt
    import api_server
    from api.auth import SUPABASE_JWT_SECRET

    if not SUPABASE_JWT_SECRET:
        # 조용히 통과하지 않는다 — 검증하지 못했다는 사실을 남긴다.
        print("[SKIPPED] SUPABASE_JWT_SECRET 미설정 - HTTP 층 검증 불가")
        return

    # `seed()` 가 만든 favorite_notes 가 이 클라이언트에도 보이도록, DB_PATH 는 이미
    # 파일 상단에서 스크래치로 바뀌어 있다(get_connection 이 호출 시점에 읽는다).
    client = TestClient(api_server.app)
    hdr = {"Authorization": "Bearer " + jwt.encode(
        {"sub": "qa-http-user"}, SUPABASE_JWT_SECRET, algorithm="HS256")}

    # -- 인증 경계 --
    check("토큰 없으면 401",
          client.post("/api/v1/favorites/import/preview", json={"text": "x"}).status_code, 401)
    check("잘못된 토큰이면 401",
          client.post("/api/v1/favorites/import/preview", json={"text": "x"},
                      headers={"Authorization": "Bearer bogus"}).status_code, 401)

    # -- 요청 검증(pydantic) — 함수 직접 호출로는 절대 나오지 않는 층 --
    check("text 누락은 422",
          client.post("/api/v1/favorites/import/preview", json={}, headers=hdr).status_code, 422)
    check("item_id 가 숫자가 아니면 422",
          client.post("/api/v1/favorites/import/commit",
                      json={"rows": [{"item_id": "abc"}]}, headers=hdr).status_code, 422)
    check("rows 가 리스트가 아니면 422",
          client.post("/api/v1/favorites/import/commit",
                      json={"rows": "nope"}, headers=hdr).status_code, 422)

    # -- 정상 왕복 --
    text = "%s 물건번호 1 #관심\n9999타경99999\n" % SEED_CASE
    r = client.post("/api/v1/favorites/import/preview",
                    json={"text": text, "source": "e2e"}, headers=hdr)
    check("preview 200", r.status_code, 200)
    body = r.json()
    rows = body["data"]["rows"]
    check("preview 행 2개", len(rows), 2)
    check("한국어 원문이 그대로 직렬화된다", rows[1]["raw"], "9999타경99999")
    check("태그가 JSON 배열로 온다", rows[0]["tags"], ["관심"])

    r = client.post("/api/v1/favorites/import/commit", headers=hdr, json={"rows": [
        {"item_id": ids["a"], "memo": "HTTP 메모", "tags": ["확인"], "source": "e2e"}]})
    check("commit 200", r.status_code, 200)
    cbody = r.json()
    check("추가 1건", cbody["data"]["summary"]["added"], 1)
    check("메모 기능이 켜져 있다", cbody["data"]["notes_enabled"], True)
    check("메모가 실제로 쓰였다", cbody["data"]["results"][0]["note_written"], True)

    r = client.get("/api/v1/favorites", headers=hdr)
    check("조회 200", r.status_code, 200)
    listed = r.json()["data"]
    check("담은 1건이 보인다", len(listed), 1)
    check("메모가 왕복한다", listed[0]["memo"], "HTTP 메모")
    check("태그가 배열로 왕복한다", listed[0]["tags"], ["확인"])

    r = client.put("/api/v1/favorites/%d/note" % ids["a"], headers=hdr,
                   json={"memo": "고침", "tags": ["재확인"], "source": "e2e"})
    check("PUT 200", r.status_code, 200)
    check("PUT success", r.json()["success"], True)
    check("편집이 조회에 반영된다",
          client.get("/api/v1/favorites", headers=hdr).json()["data"][0]["memo"], "고침")

    # -- 사용자 격리 (다른 토큰) --
    other = {"Authorization": "Bearer " + jwt.encode(
        {"sub": "qa-http-other"}, SUPABASE_JWT_SECRET, algorithm="HS256")}
    check("다른 사용자에게는 0건",
          client.get("/api/v1/favorites", headers=other).json()["data"], [])


def test_migration_is_additive():
    """026 이 순수 가산인지 -- 기존 테이블을 고치거나 지우는 문장이 없어야 한다."""
    print("\n--- 12. migration 026 ---")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "storage", "migrations", "026_create_favorite_notes.sql")
    check("파일이 있다", os.path.exists(path), True)
    sql = open(path, encoding="utf-8-sig").read()
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    upper = body.upper()
    for banned in ("DROP ", "ALTER ", "DELETE ", "UPDATE ", "INSERT "):
        check("파괴적 문장이 없다: %s" % banned.strip(), banned in upper, False)
    check("CREATE TABLE IF NOT EXISTS 를 쓴다",
          "CREATE TABLE IF NOT EXISTS" in upper, True)
    check("인덱스도 IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS" in upper, True)


def test_export_header_contract():
    """내보내기 헤더를 **되붙일 수 있는가** -- 두 파일이 갈리면 조용히 자유형이 된다."""
    print("\n--- 13. 내보내기 <-> 가져오기 헤더 계약 ---")
    import re
    from normalizer.mylist_import import HEADER_ALIASES
    root = os.path.dirname(os.path.abspath(__file__))
    ts = open(os.path.join(root, "src", "lib", "exportList.ts"), encoding="utf-8-sig").read()
    headers = re.findall(r"header:\s*'([^']+)'", ts)
    check("내보내기 열을 읽었다(검사가 공허하지 않다)", len(headers) > 0, True)

    # 열 이름이 **있는지**만 보면 부족하다 (2026-08-31 강화).
    # `"법원": "case_no"` 처럼 잘못 매핑돼도 이름은 그대로 있어서, 예전 검사는
    # 통과하면서 되붙이기만 조용히 틀린다. 의도한 필드까지 못박는다.
    intended = {"법원": "court_name", "사건번호": "case_no",
                "물건번호": "item_no", "소재지": "address"}
    for key, field in intended.items():
        check("내보내기에 '%s' 열이 있다" % key, key in headers, True)
        check("가져오기가 '%s' 를 %s 로 읽는다" % (key, field),
              HEADER_ALIASES.get(key), field)

    # 내보내기가 내는 열 중 가져오기가 아는 것은 **전부** 의도표에 있어야 한다.
    # 새 열이 생겼는데 의미가 기록되지 않으면 다음 사람이 추측하게 된다.
    unrecorded = sorted(h for h in headers
                        if h in HEADER_ALIASES and h not in intended)
    check("의미가 기록되지 않은 공유 열이 없다", unrecorded, [])

    # 실제로 되붙여 본다 - 계약을 문자열 비교가 아니라 **동작**으로 확인한다.
    sample = {"법원": "안산지원", "사건번호": "2024타경5", "물건번호": "2",
              "소재지": "경기도 안산시 단원구 원곡동 1"}
    line = ",".join(headers) + "\n" + ",".join(sample.get(h, "") for h in headers)
    parsed = parse_mylist_text(line)
    check("우리 내보내기를 되붙이면 헤더로 읽힌다", parsed["header_detected"], True)
    row = parsed["rows"][0]
    check("되붙인 사건번호", row["case_no"], "2024타경5")
    check("되붙인 물건번호", row["item_no"], "2")
    # 법원/소재지도 살아 와야 한다 - 이 둘이 빠지면 후보 좁히기가 약해진다.
    check("되붙인 법원", row["court_name"], "안산지원")
    check("되붙인 소재지가 비지 않는다", bool(row["address"]), True)

    # 이 모듈의 주석이 가리키는 검사가 **실제로 존재하는가** (2026-08-31 신설).
    # 예전 주석은 tests/ 아래의 존재하지 않는 .mjs 계약 파일을 가리키고 있었다
    # (죽은 인용을 다시 만들지 않으려고 그 이름은 여기 적지 않는다).
    # 없는 검사를 가리키는 주석은 "지키고 있다"는 거짓 보증이 된다.
    src = open(os.path.join(root, "normalizer", "mylist_import.py"),
               encoding="utf-8-sig").read()
    cited = set(re.findall(r"`?(tests/[A-Za-z0-9_.-]+|test_[A-Za-z0-9_]+\.py)`?", src))
    check("주석이 검사 파일을 실제로 가리킨다(공허하지 않다)", len(cited) > 0, True)
    missing = sorted(c for c in cited if not os.path.exists(os.path.join(root, c)))
    check("존재하지 않는 검사 파일을 가리키지 않는다", missing, [])


if __name__ == "__main__":
    test_case_no()
    test_parser()
    test_resolve()

    conn = get_connection()
    try:
        ids = seed(conn)
    finally:
        conn.close()

    test_api(ids)
    # HTTP 층은 **notes 를 지우기 전에** 돈다 — 11번이 테이블을 DROP 하기 때문이다.
    test_http_layer(ids)
    test_notes_absent(ids)
    test_migration_is_additive()
    test_export_header_contract()

    print("\n=== %d FAIL ===" % len(failures) if failures
          else "\n=== ALL FAVORITE IMPORT TESTS PASSED ===")
    if failures:
        for f in failures:
            print("  - %s" % f)
    sys.exit(1 if failures else 0)
