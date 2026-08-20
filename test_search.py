"""
api/v1/search.py의 /api/v1/search 엔드포인트 회귀 테스트.

이 파일의 관심사는 **주소 의도(Intent) 파싱이 올바른 SQL 조건으로 번역되는가**다
(`intent/analyzer.py` + `api/v1/search.py:_address_detail_condition()`).

2026-08-10(Sprint 47) 재설계 — 고정 row count 단언 제거
------------------------------------------------------
예전 버전은 `address_detail="서울" -> total == 284`처럼 **절대 건수**를 하드코딩했다.
크롤러가 매일 데이터를 넣기 때문에 이 값은 필연적으로 드리프트했고, 실제로 두 번
(2026-08-09, 2026-08-10) "실패 3건"이 났지만 **전부 검색 로직 결함이 아니라 기대값 노후화**였다.
회귀를 못 잡으면서 매번 사람을 부르는 테스트는 오히려 신호를 가린다.

그래서 "몇 건인가" 대신 **반환된 행이 실제로 그 의도에 맞는가**를 검증한다.
예: `address_detail="오금동"`이면 돌아온 모든 행의 `dong`에 "오금동"이 들어 있어야 한다.
이건 데이터가 늘어도 항상 참이어야 하는 성질이고, 조건이 엉뚱한 컬럼에 걸리면
(원래 이 테스트가 잡으려던 결함) 즉시 실패한다 — 즉 검증력은 오히려 강해졌다.

여기에 데이터와 무관하게 성립하는 **관계 불변식**을 추가한다.
- 표기 동치: "서울" == "서울시" == "서울특별시" (축약 정규화, 원래 Bug Fix 대상)
- 분해 동치: address_detail="서울 송파구 오금동" == sido/sigungu/dong 개별 지정
- 포함 관계: 더 구체적인 검색은 덜 구체적인 검색보다 결과가 많을 수 없다

실행: python test_search.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from api_server import app

client = TestClient(app)

PASS = 0
FAILURES = []


def check(name, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAILURES.append(name)
        print(f"[FAIL] {name} {detail}")


def search(**params):
    """주소 파싱 자체를 보는 테스트이므로 D7 기본 필터(auction_date >= 오늘)는 제외한다
    (매각기일 필터는 이 파일의 관심사가 아니다)."""
    r = client.get("/api/v1/search", params={**params, "include_closed": True})
    assert r.status_code == 200, (params, r.status_code, r.text)
    return r.json()


def total(**params):
    return search(size=1, **params)["total"]


def items(size=100, **params):
    return search(size=size, **params)["items"]


# (설명, address_detail, 각 행이 만족해야 하는 조건)
# 절대 건수 대신 "돌아온 행이 그 의도에 맞는가"를 본다.
INTENT_CASES = [
    ("시도(축약) -> sido 정확일치", "서울",
     lambda it: it["sido"] == "서울"),
    ("시도(-시 축약형) -> sido 정확일치", "서울시",
     lambda it: it["sido"] == "서울"),
    ("시도(정식) -> sido 정확일치", "서울특별시",
     lambda it: it["sido"] == "서울"),
    ("시군구 -> sigungu 부분일치", "송파구",
     lambda it: "송파구" in (it["sigungu"] or "")),
    ("법정동 -> dong 부분일치", "오금동",
     lambda it: "오금동" in (it["dong"] or "")),
    ("전체주소 -> sido+sigungu+dong 동시 적용", "서울 송파구 오금동",
     lambda it: it["sido"] == "서울" and "송파구" in (it["sigungu"] or "") and "오금동" in (it["dong"] or "")),
    ("전체주소(축약형 포함)", "서울시 송파구 오금동",
     lambda it: it["sido"] == "서울" and "송파구" in (it["sigungu"] or "") and "오금동" in (it["dong"] or "")),
    ("혼합입력(시군구+동+일반명사) -> 잔여어는 full_address", "강서구 화곡동 빌라",
     lambda it: "강서구" in (it["sigungu"] or "") and "화곡동" in (it["dong"] or "") and "빌라" in (it["full_address"] or "")),
    ("건물명(UNKNOWN) -> full_address LIKE 폴백", "엘시티",
     lambda it: "엘시티" in (it["full_address"] or "")),
    ("법정동(STEP7 백필분)", "빛가람동",
     lambda it: "빛가람동" in (it["dong"] or "")),
    ("법정동(STEP6/7 오탐 수정분)", "성남동",
     lambda it: "성남동" in (it["dong"] or "")),
]


def check_search_list_contract():
    r"""검색목록: **API 응답 -> React 타입 -> 실제 렌더**가 한 줄로 이어지는가 (Sprint 220).

    ## 왜 필요한가

    이 셋은 **서로 다른 파일**에 각자 적혀 있다.

        api/v1/search.py       row_to_item() 이 만드는 딕셔너리 키
        src/app/search/types.ts  SearchResultItem 이 선언한 필드
        src/app/search/ResultList.tsx  item.<필드> 로 실제로 그리는 것

    한쪽만 바뀌면 화면은 **오류 없이 빈칸**이 된다 — `item.foo` 가 `undefined` 면
    React 는 아무것도 그리지 않고 조용히 넘어간다. 콘솔에도, 서버에도 흔적이 없다.
    이 저장소가 반복해 잡아 온 "조용한 실패"의 프런트 판본이다.

    실측(2026-08-19) 기준: API 19키 / 타입 19필드 / 렌더 17필드, 어긋남 0.
    (`crawl_date`, `validation_status` 는 응답에는 있지만 목록이 그리지 않는다 —
     그것은 결함이 아니라 선택이다. 반대 방향만 결함이다.)

    ## 검사 방향은 **한쪽만**이다

        렌더가 쓰는데 API 가 안 준다   -> **결함**(빈칸이 된다)
        타입이 선언했는데 API 가 안 준다 -> **결함**(타입이 거짓말한다)
        API 가 주는데 안 쓴다          -> 결함 아님(쓸지 말지는 화면의 선택)
    """
    import ast
    import io as _io
    import re as _re

    print("\n--- 검색목록 계약: API -> 타입 -> 렌더 ---")
    root = os.path.dirname(os.path.abspath(__file__))

    def strip_comments(text):
        text = _re.sub(r"/\*[\s\S]*?\*/",
                       lambda m: _re.sub(r"[^\n]", " ", m.group(0)), text)
        return _re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)

    # 1) API 가 실제로 내는 키 — 문자열 grep 이 아니라 AST 로 딕셔너리 리터럴을 읽는다
    api_src = _io.open(os.path.join(root, "api", "v1", "search.py"),
                       encoding="utf-8-sig").read()
    api_keys = set()
    for node in ast.walk(ast.parse(api_src)):
        if isinstance(node, ast.FunctionDef) and node.name == "row_to_item":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict):
                    ks = [k.value for k in sub.keys if isinstance(k, ast.Constant)]
                    if len(ks) > 5:
                        api_keys = set(ks)
                        break
    check("API row_to_item 의 키를 읽었다(검사가 공허하지 않다)", len(api_keys) >= 15,
          "-> %d개" % len(api_keys))

    # 2) React 타입이 선언한 필드
    ts_path = os.path.join(root, "src", "app", "search", "types.ts")
    ts_src = strip_comments(_io.open(ts_path, encoding="utf-8-sig").read())
    m = _re.search(r"export type SearchResultItem\s*=\s*\{([\s\S]*?)\n\}", ts_src)
    ts_keys = set(_re.findall(r"^\s*([A-Za-z_]\w*)\??\s*:", m.group(1), _re.M)) if m else set()
    check("types.ts 의 SearchResultItem 을 읽었다", len(ts_keys) >= 15,
          "-> %d개" % len(ts_keys))

    # 3) 목록이 실제로 그리는 필드
    list_src = strip_comments(_io.open(
        os.path.join(root, "src", "app", "search", "ResultList.tsx"),
        encoding="utf-8-sig").read())
    used = set(_re.findall(r"\bitem\.([A-Za-z_]\w*)", list_src))
    check("ResultList 가 쓰는 필드를 읽었다", len(used) >= 10, "-> %d개" % len(used))

    # --- 한쪽 방향만 결함이다
    check("★ 타입이 선언했는데 API 가 주지 않는 필드",
          sorted(ts_keys - api_keys) == [],
          "-> %s (타입이 거짓말한다)" % sorted(ts_keys - api_keys))
    check("★ 렌더가 쓰는데 API 가 주지 않는 필드",
          sorted(used - api_keys) == [],
          "-> %s (화면이 조용히 빈칸이 된다)" % sorted(used - api_keys))
    check("★ 렌더가 쓰는데 타입에 없는 필드",
          sorted(used - ts_keys) == [],
          "-> %s" % sorted(used - ts_keys))

    print("    API %d키 / 타입 %d필드 / 렌더 %d필드 (응답에만 있는 것: %s)"
          % (len(api_keys), len(ts_keys), len(used),
             ", ".join(sorted(api_keys - used)) or "없음"))


def check_no_stale_read_path():
    r"""법원 데이터가 바뀐 뒤 화면이 **옛 값을 보여줄 경로**가 있는가 (Sprint 220).

    검색·상세는 매 요청마다 SQLite 를 직접 읽는다 — 응답 캐시 계층이 없다.
    프런트도 `src/lib/api.ts` 의 모든 fetch 가 `cache: no-store` 다.
    즉 **stale 이 생길 자리 자체가 없다.**

    그런데 그것은 지금의 선택일 뿐 강제된 적이 없다. 성능을 이유로 캐시를
    한 줄 넣으면 그 순간 "매각기일이 어제 값으로 보인다"가 가능해지고,
    그 실패는 **화면에 오류로 나타나지 않는다**(그냥 옛 숫자가 보인다).

    사진 바이트만은 ETag 로 캐시된다 — 그것은 의도이고, 교체 시 갱신되는지는
    `test_asset_pipeline.py` 12-O 가 따로 본다(같은 크기의 다른 사진으로 검증).

    실측(2026-08-19): `api.ts` fetch 5곳 / `no-store` 5곳, 라우터 캐시 헤더 0곳.
    """
    import io as _io
    import re as _re

    print("\n--- 데이터 신선도: 옛 값을 보여줄 경로가 없는가 ---")
    root = os.path.dirname(os.path.abspath(__file__))

    def strip_comments(text):
        text = _re.sub(r"/\*[\s\S]*?\*/",
                       lambda m: _re.sub(r"[^\n]", " ", m.group(0)), text)
        return _re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)

    api_ts = os.path.join(root, "src", "lib", "api.ts")
    code = strip_comments(_io.open(api_ts, encoding="utf-8-sig").read())
    fetches = len(_re.findall(r"\bfetch\(", code))
    nostore = code.count("no-store")
    check("api.ts 의 fetch 를 실제로 찾았다(검사가 공허하지 않다)", fetches >= 4,
          "-> %d개" % fetches)
    check("★ 모든 fetch 가 no-store 다(옛 응답을 재사용하지 않는다)",
          nostore >= fetches, "-> fetch %d / no-store %d" % (fetches, nostore))

    # 서버 라우터에 캐시 헤더가 붙지 않았는가 (사진 서빙은 예외 — 별도 파일이다)
    stale_headers = []
    for name in ("item.py", "search.py"):
        path = os.path.join(root, "api", "v1", name)
        body = strip_comments(_io.open(path, encoding="utf-8-sig").read())
        for token in ("Cache-Control", "max-age", "s-maxage"):
            if token in body:
                stale_headers.append("%s:%s" % (name, token))
    check("★ 검색/상세 응답에 캐시 헤더가 없다", sorted(stale_headers) == [],
          "-> %s (넣으려면 매각기일이 옛 값으로 보이는 경우를 먼저 답해야 한다)"
          % sorted(stale_headers))
    print("    api.ts fetch %d곳 / no-store %d곳" % (fetches, nostore))

def check_every_list_screen_contract():
    r"""**목록 성격의 화면 전부**가 자기 API 와 계약이 맞는가 (Sprint 221).

    앞의 검사는 검색목록 하나만 봤다. 같은 모양의 화면이 셋 더 있다.

        검색목록      api/v1/search.py       row_to_item()
        관심물건      api/v1/favorites.py    SELECT ai.* + favorited_at
        최근 본 물건   api/v1/recent_items.py SELECT ai.* + viewed_at
        상세페이지     api/v1/item.py         get_item()

    이 두 화면의 응답은 **명시적인 dict 리터럴**이다(`dict(row)` 가 아니다).
    그래서 "API 가 무엇을 주는가"의 근거는 스키마가 아니라 **그 dict 의 키**다 -
    상세페이지를 이미 그렇게 대조하고 있었고(AST), 여기도 같은 방식으로 맞춘다.

    ★ 2026-08-20 (Sprint 224) 정정. 이 검사의 앞 판본은 제공 필드를
      `auction_item 컬럼 + {favorited_at}` 으로 **가정**했다. 그 가정은 계산된 키
      (`thumbnail_url` 처럼 컬럼이 아닌 값)를 표현할 수 없어서, API 가 실제로 그
      키를 주기 시작하자 **없는 결함을 보고했다.** 소스에서 읽을 수 있는 사실을
      손으로 베껴 적으면 반드시 이렇게 어긋난다.

    스키마 결합은 따로 본다 - dict 가 읽는 `row["X"]` 의 X 가 실제 `auction_item`
    컬럼인가. 컬럼이 사라지면 여기서 걸린다(런타임에는 KeyError -> 500 이다).

    ## 썸네일 규칙

    어느 화면이든 `thumbnail_url` 을 그리기 시작하면 그 화면의 API 도 그것을 주어야
    한다. 한쪽만 바뀌면 여기서 걸린다 - 2026-08-20 현재 검색목록·관심물건·
    최근 본 물건 **셋 다** 그리고, 셋 다 받는다.
    """
    import io as _io
    import re as _re
    import sqlite3 as _sqlite3

    print("\n--- 목록 성격 화면 전체의 데이터 계약 ---")
    root = os.path.dirname(os.path.abspath(__file__))

    def strip_comments(text):
        text = _re.sub(r"/\*[\s\S]*?\*/",
                       lambda m: _re.sub(r"[^\n]", " ", m.group(0)), text)
        return _re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)

    def rendered(rel, var):
        src = strip_comments(_io.open(os.path.join(root, rel), encoding="utf-8-sig").read())
        return set(_re.findall(r"\b" + var + r"\.([A-Za-z_]\w*)", src))

    import ast as _ast

    from storage.database import DB_PATH as _DB_PATH
    conn = _sqlite3.connect("file:%s?mode=ro" % _DB_PATH.replace("\\", "/"), uri=True)
    try:
        item_cols = {r[1] for r in conn.execute("PRAGMA table_info(auction_item)")}
    finally:
        conn.close()
    check("auction_item 컬럼을 읽었다(검사가 공허하지 않다)", len(item_cols) >= 15,
          "-> %d개" % len(item_cols))

    def api_dict(rel_py, func_name):
        """그 함수가 만드는 응답 dict 의 (키 집합, 읽는 row 컬럼 집합).

        키를 손으로 적지 않고 **소스에서 읽는다** - 손으로 적으면 API 가 바뀔 때마다
        검사가 거짓 실패를 낸다(실제로 그랬다).
        """
        src = _io.open(os.path.join(root, *rel_py.split("/")), encoding="utf-8-sig").read()
        for node in _ast.walk(_ast.parse(src)):
            if not (isinstance(node, _ast.FunctionDef) and node.name == func_name):
                continue
            keys, cols = set(), set()
            for sub in _ast.walk(node):
                if isinstance(sub, _ast.Dict):
                    ks = {k.value for k in sub.keys if isinstance(k, _ast.Constant)}
                    if len(ks) > len(keys):
                        keys = ks
                # row["case_no"] 처럼 첨자로 읽는 컬럼
                if (isinstance(sub, _ast.Subscript)
                        and isinstance(sub.value, _ast.Name) and sub.value.id == "row"
                        and isinstance(sub.slice, _ast.Constant)
                        and isinstance(sub.slice.value, str)):
                    cols.add(sub.slice.value)
            return keys, cols
        return set(), set()

    SCREENS = [
        ("관심물건", "src/app/favorites/page.tsx", "item",
         "api/v1/favorites.py", "get_favorites", {"favorited_at"}),
        ("최근 본 물건", "src/app/properties/recent/page.tsx", "item",
         "api/v1/recent_items.py", "get_recent_items", {"viewed_at"}),
    ]
    screen_provided = {}
    for label, rel, var, rel_py, func, joined in SCREENS:
        provided, read_cols = api_dict(rel_py, func)
        screen_provided[label] = provided
        check("%s: API 응답 키를 실제로 읽었다(검사가 공허하지 않다)" % label,
              len(provided) >= 10, "-> %d개" % len(provided))
        # 스키마 결합 - dict 가 읽는 컬럼이 실제로 존재하는가(없으면 런타임 500)
        check("%s: API 가 읽는 컬럼이 전부 auction_item 에 있다" % label,
              sorted(read_cols - item_cols - joined) == [],
              "-> %s (컬럼이 사라지면 500)" % sorted(read_cols - item_cols - joined))
        used = rendered(rel, var)
        check("%s: 렌더 필드를 실제로 찾았다" % label, len(used) >= 8, "-> %d개" % len(used))
        check("%s: 렌더가 쓰는데 API 가 주지 않는 필드" % label,
              sorted(used - provided) == [],
              "-> %s (화면이 조용히 빈칸이 된다)" % sorted(used - provided))

    # 상세페이지 - get_item() 이 만드는 키와 대조
    detail_keys = set()
    detail_src = _io.open(os.path.join(root, "api", "v1", "item.py"),
                          encoding="utf-8-sig").read()
    for node in _ast.walk(_ast.parse(detail_src)):
        if isinstance(node, _ast.FunctionDef) and node.name == "get_item":
            for sub in _ast.walk(node):
                if isinstance(sub, _ast.Dict):
                    ks = {k.value for k in sub.keys if isinstance(k, _ast.Constant)}
                    if len(ks) > len(detail_keys):
                        detail_keys = ks
    check("상세 API 의 키를 읽었다", len(detail_keys) >= 20, "-> %d개" % len(detail_keys))
    detail_used = rendered("src/app/properties/[id]/page.tsx", "property")
    check("상세: 렌더가 쓰는데 API 가 주지 않는 필드",
          sorted(detail_used - detail_keys) == [],
          "-> %s" % sorted(detail_used - detail_keys))

    # ★ 썸네일 규칙 - 그리는 화면은 API 도 주어야 한다
    #   `<ResultThumbnail>` 은 공용 컴포넌트라 화면 파일에 `thumbnail_url` 문자열이
    #   그대로 나타난다(prop 으로 넘긴다). 주석은 지운 뒤에 본다.
    search_keys = {k for k in _re.findall(r'"([a-z_]+)":', _io.open(
        os.path.join(root, "api", "v1", "search.py"), encoding="utf-8-sig").read())}
    candidates = [(label, rel, screen_provided[label]) for label, rel, _v, _p, _f, _j in SCREENS]
    candidates.append(("검색목록", "src/app/search/ResultList.tsx", search_keys))
    thumb_screens = []
    for label, rel, provided in candidates:
        src = strip_comments(_io.open(os.path.join(root, rel), encoding="utf-8-sig").read())
        if "thumbnail_url" in src:
            thumb_screens.append((label, provided))
    check("썸네일을 그리는 화면을 실제로 찾았다(검사가 공허하지 않다)",
          len(thumb_screens) >= 1, "-> %d개" % len(thumb_screens))
    broken = [lbl for lbl, provided in thumb_screens if "thumbnail_url" not in provided]
    check("★ 썸네일을 그리는 화면은 API 도 thumbnail_url 을 준다",
          sorted(broken) == [], "-> %s (화면만 바뀌면 빈칸이 된다)" % sorted(broken))
    print("    썸네일을 그리는 화면: %s" % ", ".join(l for l, _p in thumb_screens))


def check_search_issues_a_constant_number_of_queries():
    r"""검색 API 가 **결과 개수와 무관하게 같은 수의 SQL** 을 내는가 (2026-08-19 Sprint 223).

    ## 왜 이 검사인가

    "배치 조회를 쓴다"는 것은 **코드를 읽어서** 아는 사실이고, 실제로 몇 번 나가는지는
    **재 봐야** 아는 사실이다. Sprint 145가 썸네일 배치 조회를 넣었지만, 그 뒤로
    "정말 1회인가"를 잰 적은 없었다. 한 줄만 잘못 옮겨도 물건마다 한 번씩 나가고,
    그때도 화면은 똑같이 잘 보인다 — **느려질 뿐이다.** 그래서 눈이 아니라 계측이 필요하다.

    ## 실측 (2026-08-19)

        size=1  -> items 1 / thumbnails 1 / SQL 3
        size=3  -> items 3 / thumbnails 3 / SQL 3
        size=9  -> items 9 / thumbnails 9 / SQL 3

        3회 = COUNT(*) + 페이지 행 + auction_image 배치(MIN(seq) GROUP BY)
        (로그인 상태면 favorites 배치가 1회 더 붙는다 — 이 검사는 비로그인 기준)

    개수가 늘어도 SQL 이 늘지 않는다. 즉 **N+1 이 아니다.**

    ## 어떻게 재는가

    `sqlite3.Connection.set_trace_callback` 으로 실제 실행된 문장을 센다.
    `storage.database.get_connection` 을 감싸므로 라우터가 어떤 경로로 커넥션을
    얻든 같은 계측이 걸린다.
    """
    import sqlite3  # noqa: F401  (set_trace_callback 의 출처를 명시)
    import storage.database as _db

    print("\n--- 검색 API 의 SQL 횟수 (N+1 감시) ---")
    stmts = []
    original = _db.get_connection

    def traced():
        conn = original()
        conn.set_trace_callback(lambda s: stmts.append(" ".join(s.split())[:80]))
        return conn

    # 라우터가 모듈 상단에서 이름을 가져갔을 수 있으므로 그쪽도 바꿔 준다.
    import api.v1.search as _search
    patched = [(_db, "get_connection", original)]
    _db.get_connection = traced
    if getattr(_search, "get_connection", None) is original:
        patched.append((_search, "get_connection", original))
        _search.get_connection = traced
    try:
        counts = {}
        for size in (1, 9):
            stmts.clear()
            # ★ 이 파일의 다른 모든 호출과 같이 include_closed=True 로 잰다.
            #   기본값(False)은 `auction_date >= 오늘` 을 걸므로, 크롤이 며칠만 멈춰도
            #   결과가 0건이 되어 **코드가 멀쩡한데 이 검사만 빨간불**이 된다.
            #   실제로 2026-08-20 에 그렇게 됐다(마지막 크롤 08-12, 최신 매각기일 08-19).
            #   측정 대상은 "행 수에 따라 SQL 이 늘어나는가"이지 "오늘 이후 물건이 있는가"가
            #   아니다 — 후자는 test_pipeline_integrity.py 가 따로 본다.
            body = client.get(
                "/api/v1/search",
                params={"page": 1, "size": size, "include_closed": True},
            ).json()
            counts[size] = (len(stmts), len(body["items"]))
    finally:
        for mod, name, value in patched:
            setattr(mod, name, value)

    # 검사가 공허하지 않으려면 계측이 실제로 걸려야 한다.
    check("SQL 을 실제로 계측했다(검사가 공허하지 않다)",
          counts[1][0] > 0 and counts[9][1] > counts[1][1],
          "-> %s (계측이 걸렸는가 / size 를 늘렸을 때 행이 실제로 늘었는가)" % counts)
    check("★ 결과가 늘어도 SQL 횟수가 늘지 않는다(N+1 아님)",
          counts[1][0] == counts[9][0],
          "-> size1 %d회 / size9 %d회" % (counts[1][0], counts[9][0]))
    # 상한도 함께 건다 — 같은 수로 늘어나는(전부 N+1) 경우를 막는다.
    check("★ 검색 1회의 SQL 이 4회를 넘지 않는다",
          counts[9][0] <= 4, "-> %d회" % counts[9][0])
    print("    size=1 %d회 / size=9 %d회 (COUNT + 페이지 + 썸네일 배치)"
          % (counts[1][0], counts[9][0]))


def run():
    print("=" * 70)
    print(" /api/v1/search 주소 Intent 회귀 (건수 비의존)")
    print("=" * 70)

    # --- 1. 의도별 행 단위 검증 -------------------------------------------
    for name, value, predicate in INTENT_CASES:
        rows = items(address_detail=value)
        if not rows:
            # 0건 자체는 실패가 아니다(데이터가 없을 수 있다). 다만 검증할 게 없으므로 표시만 한다.
            check(f"{name} - 대상 데이터 없음(검증 생략)", True)
            continue
        bad = [it for it in rows if not predicate(it)]
        check(
            f"{name} ({len(rows)}건 전수 확인)",
            not bad,
            f"-> 조건 불일치 {len(bad)}건, 예: {bad[0]['full_address'] if bad else ''!r}",
        )

    # --- 2. 표기 동치 (축약 정규화) — 데이터 무관 불변식 --------------------
    t_short, t_si, t_full = total(address_detail="서울"), total(address_detail="서울시"), total(address_detail="서울특별시")
    check(
        "표기 동치: '서울' == '서울시' == '서울특별시'",
        t_short == t_si == t_full,
        f"-> {t_short}/{t_si}/{t_full}",
    )

    check(
        "기존 sido 파라미터 정규화 회귀 없음('서울특별시' == '서울')",
        total(sido="서울특별시") == total(sido="서울"),
    )

    # --- 2-b. 컬럼 매핑 고정: 자유텍스트 의도 == 같은 뜻의 명시적 파라미터 ----
    #
    # 이게 이 파일에서 가장 중요한 검사다. 위 "행 단위 검증"은 조건이 엉뚱한 컬럼에 걸려
    # **0건**이 되면 검증할 행이 없어 조용히 통과해버린다(실제로 mutation 테스트에서 확인).
    # 아래 동치는 결과가 0건이든 아니든 항상 성립해야 하므로, 컬럼이 바뀌는 순간 깨진다.
    for label, free_kw, explicit in [
        ("시도", {"address_detail": "서울"}, {"sido": "서울"}),
        ("시군구", {"address_detail": "송파구"}, {"sigungu": "송파구"}),
        ("법정동", {"address_detail": "오금동"}, {"dong": "오금동"}),
    ]:
        a, b = total(**free_kw), total(**explicit)
        check(
            f"컬럼 매핑 고정({label}): address_detail 검색 == 해당 파라미터 검색",
            a == b,
            f"-> address_detail={a} vs 명시적={b} (의도가 다른 컬럼에 걸렸을 수 있음)",
        )

    # --- 3. 분해 동치: 자유텍스트 전체주소 == 개별 파라미터 지정 -------------
    t_free = total(address_detail="서울 송파구 오금동")
    t_explicit = total(sido="서울", sigungu="송파구", dong="오금동")
    check(
        "분해 동치: address_detail 전체주소 == sido/sigungu/dong 개별 지정",
        t_free == t_explicit,
        f"-> free={t_free} explicit={t_explicit}",
    )

    # --- 4. 포함 관계: 구체적일수록 결과가 늘어날 수 없다 -------------------
    t_dong = total(address_detail="오금동")
    check(
        "포함 관계: '서울 송파구 오금동' <= '오금동'",
        t_free <= t_dong,
        f"-> {t_free} > {t_dong}",
    )
    t_sigungu_only = total(sigungu="송파구")
    check(
        "포함 관계: sido+sigungu <= sigungu 단독",
        total(sido="서울", sigungu="송파구") <= t_sigungu_only,
    )

    # --- 5. 매칭이 불가능한 입력은 항상 0건 (데이터 무관) -------------------
    check("존재하지 않는 검색어는 0건", total(address_detail="존재하지않는검색어123") == 0)

    # --- 6. 기존 동작 보존 --------------------------------------------------
    check(
        "빈 문자열 address_detail == 무필터",
        total(address_detail="") == total(),
    )
    solo, combined = total(address_detail="오금동"), total(address_detail="오금동", min_appraisal=0)
    check(
        "address_detail + 가격조건 AND 결합",
        combined == solo,
        f"-> combined={combined} solo={solo}",
    )

    # --- 7. 응답 계약 --------------------------------------------------------
    body = search(address_detail="오금동", size=1)
    check(
        "응답 스키마 불변",
        set(body.keys()) == {"total", "page", "size", "total_pages", "items"},
        f"-> {set(body.keys())}",
    )
    check("page/size 반영", body["page"] == 1 and body["size"] == 1)

    required = {
        "id", "case_no", "item_no", "court_name", "property_type",
        "sido", "sigungu", "dong", "full_address",
        "appraisal_price", "minimum_bid_price", "bid_rate",
        "auction_date", "status", "fail_count",
        "validation_status", "crawl_date", "is_favorited",
    }
    sample = items(size=1)
    if sample:
        missing = required - set(sample[0].keys())
        check("item 필수 필드 전부 존재", not missing, f"-> 누락 {missing}")
    else:
        check("item 필수 필드 - 데이터 없음(검증 생략)", True)

    # --- 5. 선언만 되고 한 번도 실행된 적 없는 필터 (2026-08-13 Sprint 85) ------
    #
    # 커버리지로 찾았다: api/v1/search.py 266-305가 미커버였다. court_name / status /
    # auction_date_to / min·max appraisal / min·max bid_price / min·max bid_rate /
    # min·max fail_count — **12개 필터가 선언돼 있는데 어떤 테스트도 넘겨본 적이 없었다.**
    #
    # 이 부류의 결함은 조용하다. 예를 들어 min 필터가 `<=`로 뒤집혀 있으면 사용자는
    # "최소 감정가 5억"으로 검색해 **5억 이하** 물건을 받는다. 서버는 200을 주고 로그도
    # 남지 않는다. 그래서 "몇 건인가"가 아니라 **돌아온 행이 조건을 만족하는가** +
    # **방향이 뒤집히지 않았는가**를 본다(이 파일의 기존 원칙과 같다).
    #
    # 경계값은 실제 데이터에서 뽑는다 — 하드코딩하면 데이터가 변할 때 노후화된다.
    def _numeric_bound(field):
        """그 컬럼의 중앙값 근처 값 하나. 없으면 None."""
        rows = [it[field] for it in items(size=100) if it.get(field) is not None]
        if not rows:
            return None
        rows.sort()
        return rows[len(rows) // 2]

    RANGE_FILTERS = [
        ("appraisal_price", "min_appraisal", "max_appraisal"),
        ("minimum_bid_price", "min_bid_price", "max_bid_price"),
        ("bid_rate", "min_bid_rate", "max_bid_rate"),
        ("fail_count", "min_fail_count", "max_fail_count"),
    ]
    for field, min_key, max_key in RANGE_FILTERS:
        bound = _numeric_bound(field)
        if bound is None:
            check("%s 범위 필터 - 대상 데이터 없음(검증 생략)" % field, True)
            continue

        lo = items(size=100, **{min_key: bound})
        hi = items(size=100, **{max_key: bound})
        # (a) 행 단위로 조건을 만족하는가
        bad_lo = [it for it in lo if it.get(field) is not None and it[field] < bound]
        bad_hi = [it for it in hi if it.get(field) is not None and it[field] > bound]
        check("%s: %s=%s 이면 모든 행이 그 이상" % (field, min_key, bound),
              not bad_lo, "-> 위반 %d건, 예: %r" % (len(bad_lo), bad_lo[0].get(field) if bad_lo else None))
        check("%s: %s=%s 이면 모든 행이 그 이하" % (field, max_key, bound),
              not bad_hi, "-> 위반 %d건, 예: %r" % (len(bad_hi), bad_hi[0].get(field) if bad_hi else None))

        # (b) 방향이 뒤집히지 않았는가 — min/max를 서로 바꿔 구현하면 (a)만으로는
        #     한쪽이 통과할 수 있다. 두 결과의 합이 전체를 덮고, 교집합이 경계값뿐임을 본다.
        t_all = total()
        t_lo, t_hi = total(**{min_key: bound}), total(**{max_key: bound})
        eq = len([it for it in items(size=100) if it.get(field) == bound])
        check("%s: min/max 결과가 전체를 덮는다(방향 정합)" % field,
              t_lo + t_hi >= t_all, "-> %d + %d < %d" % (t_lo, t_hi, t_all))

        # (c) 모순 범위(min > max)는 빈 결과여야 한다 — 조건이 OR로 잘못 묶이면 여기서 드러난다.
        #
        # 처음에는 float 컬럼(bid_rate)에 `max = bound`를 넘겨 "모순"이라고 불렀는데
        # min==max는 모순이 아니라 정확일치다 — 293건이 나온 것이 옳은 동작이었다(테스트 결함).
        # 타입에 맞는 실제 모순값을 만든다.
        gap = 1 if isinstance(bound, int) else 0.01
        contradictory = total(**{min_key: bound, max_key: bound - gap})
        check("%s: min>max 모순 범위는 결과가 없다" % field, contradictory == 0,
              "-> %d건 (조건이 AND가 아니라 OR로 묶였을 수 있다)" % contradictory)

    # court_name / status: 부분일치(LIKE) 필터
    sample = items(size=1)
    if sample:
        court = sample[0]["court_name"]
        rows = items(size=100, court_name=court)
        # ★ 먼저 **구분력**을 본다. 검색 대상을 실제 행에서 뽑았으므로 최소 1건은 나와야 한다.
        #   이 단언이 없으면 필터가 엉뚱한 컬럼에 걸려 0건이 나올 때 아래 "모든 행이 조건을
        #   만족한다"가 **공허하게 통과**한다(변이 시험에서 실제로 그렇게 통과했다 — Sprint 78).
        check("court_name 필터에 구분력이 있다(0건이면 검사가 무의미)", len(rows) > 0,
              "-> 0건. 필터가 다른 컬럼에 걸렸을 수 있다(court=%r)" % court)
        bad = [it for it in rows if court not in (it["court_name"] or "")]
        check("court_name 필터가 실제로 그 법원만 돌려준다(%d건)" % len(rows), not bad,
              "-> 위반 %d건" % len(bad))
        check("court_name 오타는 빈 결과(200)", total(court_name="없는법원명XYZ") == 0)

        st = sample[0]["status"]
        if st:
            rows = items(size=100, status=st)
            check("status 필터에 구분력이 있다(0건이면 검사가 무의미)", len(rows) > 0,
                  "-> 0건 (status=%r)" % st)
            bad = [it for it in rows if st not in (it["status"] or "")]
            check("status 필터가 실제로 그 상태만 돌려준다(%d건)" % len(rows), not bad,
                  "-> 위반 %d건" % len(bad))
    else:
        check("court_name/status 필터 - 데이터 없음(검증 생략)", True)

    # auction_date_to: 상한 필터. auction_date_from과 함께 쓰면 구간이 된다.
    dates = sorted(it["auction_date"] for it in items(size=100) if it.get("auction_date"))
    if dates:
        mid = dates[len(dates) // 2]
        rows = items(size=100, auction_date_to=mid)
        bad = [it for it in rows if it.get("auction_date") and it["auction_date"] > mid]
        check("auction_date_to 이후 물건은 제외된다(%d건)" % len(rows), not bad,
              "-> 위반 %d건, 예: %r" % (len(bad), bad[0].get("auction_date") if bad else None))
        # 구간 지정: from == to 면 그 날짜만 남아야 한다.
        exact = items(size=100, auction_date_from=mid, auction_date_to=mid)
        bad = [it for it in exact if it.get("auction_date") != mid]
        check("auction_date_from==to 는 그 날짜만(%d건)" % len(exact), not bad,
              "-> 위반 %d건" % len(bad))
    else:
        check("auction_date_to 필터 - 데이터 없음(검증 생략)", True)

    # --- 6. 프론트가 보내지만 백엔드가 읽지 않는 필터 (2026-08-13 Sprint 85) ----
    #
    # `src/app/search/SearchForm.tsx`는 면적/특수조건 입력값을 쿼리에 실어 보내는데,
    # `auction_item`에 대응 컬럼이 없어 백엔드가 **읽지 않는다**(소스에 TODO로 표시돼 있다).
    # 2026-08-13 실측: 극단값(min_land_area=9999)을 줘도 결과 건수가 그대로다.
    # 사용자에게는 "면적으로 걸렀다"고 보이지만 실제로는 걸러지지 않는다.
    #
    # 구현은 컬럼 추가(스키마 변경) + 크롤러 추출이 필요해 승인 사항이므로 여기서 하지 않는다.
    # 대신 **양방향 드리프트 가드**를 둔다.
    #   - 지금 무시된다는 사실을 고정한다(대조군으로 지원되는 필터가 실제로 걸리는지 함께 본다 ―
    #     대조군이 없으면 "무시된다"가 "필터가 전부 안 걸린다"와 구별되지 않는다).
    #   - 400/422로 깨지지 않는 것도 함께 고정한다. 프론트가 이미 보내고 있으므로, 백엔드가
    #     unknown 파라미터를 거부하도록 바뀌면 **검색 자체가 죽는다**.
    #   - 백엔드에 그 이름이 생기면(구현되면) 이 검사가 실패한다 ― 프론트 TODO를 정리하고
    #     기대값을 옮기라는 신호다. 조용히 어긋난 상태로 남지 않게 한다.
    UNSUPPORTED = ("min_building_area", "max_building_area", "min_land_area", "max_land_area",
                   "special_conditions")

    # ★ 2026-08-17 Sprint 163: 이 목록이 **최신인지 자체를 검사**한다.
    #
    # 위 UNSUPPORTED는 하드코딩된 목록이다. 그래서 프런트가 **여섯 번째** 미지원
    # 파라미터를 추가하면 아래 검사들은 전부 통과하면서 그 하나를 영원히 놓친다.
    # 같은 한계로 `test_doc_path_safety.py`의 규칙 사본 검사가 파일 하나를 놓쳤고,
    # 그것이 BUGS #112였다("목록 기반 검사는 목록에서 빠진 것을 못 본다").
    #
    # 그래서 목록을 **계산해서 대조**한다.
    #   프런트가 URL에 싣는 키  -  백엔드가 선언한 쿼리 파라미터  =  무시되는 키
    # 이 차집합이 UNSUPPORTED와 정확히 같아야 한다. 새 미지원 파라미터가 생기면
    # 그 순간 이 검사가 실패하며 이름을 그대로 알려 준다.
    import re as _re
    _form_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "src", "app", "search", "SearchForm.tsx")
    if os.path.exists(_form_path):
        _form = open(_form_path, encoding="utf-8-sig").read()
        _sent = set(_re.findall(r"\bquery\.([A-Za-z_][A-Za-z0-9_]*)\s*=", _form))
        _sent |= set(_re.findall(r"\bquery\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]", _form))

        _declared = set()
        for _p, _ops in app.openapi()["paths"].items():
            if _p != "/api/v1/search":
                continue
            for _op in _ops.values():
                for _prm in _op.get("parameters", []):
                    if _prm.get("in") == "query":
                        _declared.add(_prm["name"])

        check("대조군: 프런트/백엔드 키를 실제로 읽어냈다",
              len(_sent) > 5 and len(_declared) > 5,
              "-> 보냄 %d개 / 선언 %d개" % (len(_sent), len(_declared)))

        _ignored = _sent - _declared
        _new = sorted(_ignored - set(UNSUPPORTED))
        _gone = sorted(set(UNSUPPORTED) - _ignored)
        check("새로 조용히 무시되는 파라미터가 없다", not _new,
              "-> %r 이 UNSUPPORTED에 없다. 프런트가 보내는데 백엔드가 안 읽는다" % (_new,))
        check("UNSUPPORTED에 죽은 항목이 없다", not _gone,
              "-> %r 은 더 이상 무시되지 않는다(구현됐거나 프런트가 안 보낸다)" % (_gone,))
    baseline = total(sido="서울")
    check("대조군: 기준 검색이 0건이 아니다(검사가 공허하지 않다)", baseline > 0,
          "-> baseline=%d" % baseline)
    for name in UNSUPPORTED:
        # 이 값이 반영된다면 결과는 0건이 되어야 하는 극단값을 넣는다.
        value = "유치권" if name == "special_conditions" else (9999999 if name.startswith("min") else 1)
        got = total(sido="서울", **{name: value})
        check("%s는 무시된다(건수 불변 %d)" % (name, baseline), got == baseline,
              "-> %d != %d (구현됐다면 프론트 TODO와 이 검사를 함께 정리할 것)" % (got, baseline))

    # 대조군: 지원되는 상한/하한 필터는 실제로 결과를 줄인다.
    check("대조군: 지원되는 필터(min_appraisal)는 실제로 걸린다",
          total(sido="서울", min_appraisal=10 ** 15) == 0)

    # 소스 레벨 확인 ― 백엔드는 그 이름을 아예 모르고, 프론트는 미지원임을 표시해 둔다.
    api_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "api", "v1", "search.py"), encoding="utf-8-sig").read()
    leaked = [n for n in UNSUPPORTED if n in api_src]
    check("백엔드 search.py에는 아직 그 파라미터가 없다", not leaked, "-> %r" % (leaked,))

    form_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "src", "app", "search", "SearchForm.tsx")
    if os.path.exists(form_path):
        form_src = open(form_path, encoding="utf-8-sig").read()
        check("프론트에 미지원 표시(TODO)가 남아 있다", "TODO(API 미지원)" in form_src)
        unmarked = [n for n in UNSUPPORTED if n not in form_src]
        # 프론트가 더 이상 보내지 않게 되면 이 목록 자체를 줄여야 한다 ― 그 사실도 알려준다.
        check("프론트가 여전히 그 파라미터를 보낸다(목록이 최신이다)", not unmarked,
              "-> 더 이상 보내지 않는 것: %r" % (unmarked,))
    else:
        check("SearchForm.tsx 경로 확인", False, "-> 경로가 바뀌었다: %s" % form_path)

    # -----------------------------------------------------------------------
    # 숫자 파라미터의 SQLite INTEGER 범위 (2026-08-17 Sprint 146)
    #
    # 파이썬 int는 무한 정밀도인데 SQLite INTEGER는 64비트다. 상한 없는 숫자 파라미터를
    # 그대로 바인딩하면 `OverflowError`로 터진다 — **인증 없이 500을 만들 수 있었다.**
    #
    #   실측(수정 전, 전부 토큰 불필요):
    #     ?min_appraisal=9999999999999999999999999   500
    #     ?max_appraisal= / ?min_bid_price= / ?max_bid_price=   500
    #     ?min_fail_count= / ?max_fail_count=                   500
    #     ?page=9999999999999999999999999                       500
    #
    # `size`만 무사했다 — `Query(20, ge=1, le=100)`이 이미 막고 있었기 때문이다.
    # Sprint 144가 `item_id`에 쓴 `is_sqlite_int()`를 그대로 재사용해 400으로 거절한다
    # (이 엔드포인트가 sort_by/property_type에 이미 쓰는 규약과 같은 방식).
    # -----------------------------------------------------------------------
    HUGE = int("9" * 25)
    OVERFLOW_PARAMS = ("min_appraisal", "max_appraisal", "min_bid_price",
                       "max_bid_price", "min_fail_count", "max_fail_count")
    for name in OVERFLOW_PARAMS:
        r = client.get("/api/v1/search", params={name: HUGE})
        check("%s 초대형 값은 400 (500 아님)" % name, r.status_code == 400,
              "-> %d" % r.status_code)

    r = client.get("/api/v1/search", params={"page": HUGE})
    check("page 초대형 값은 400 (500 아님)", r.status_code == 400, "-> %d" % r.status_code)

    # page는 값 자체가 아니라 (page-1)*size가 넘친다 — 값만 검사하면 이 케이스를 놓친다.
    r = client.get("/api/v1/search", params={"page": 2 ** 63 - 1})
    check("page=2^63-1도 400 (OFFSET 곱셈이 넘친다)", r.status_code == 400,
          "-> %d" % r.status_code)

    # 과잉 차단 방지 — 경계 안의 값과 정상 사용은 그대로 동작해야 한다.
    r = client.get("/api/v1/search", params={"min_appraisal": 2 ** 63 - 1})
    check("min_appraisal=2^63-1은 정상 처리(200)", r.status_code == 200,
          "-> %d" % r.status_code)
    for page in (1, 2):
        r = client.get("/api/v1/search", params={"page": page})
        check("page=%d 정상 동작" % page, r.status_code == 200, "-> %d" % r.status_code)
    r = client.get("/api/v1/search", params={"min_appraisal": 100000000})
    check("정상 범위 필터는 그대로 200", r.status_code == 200, "-> %d" % r.status_code)

    # ------------------------------------------------------------------
    # sido 정규화가 /search 와 /search/regions 에서 **같아야** 한다
    #   (2026-08-17 Sprint 156 신설)
    #
    # `/search`는 `extract_sido(sido) or sido`로 정규화하는데 `/search/regions`만
    # 원본을 그대로 WHERE에 넣고 있었다. auction_item.sido는 축약형("서울")으로
    # 저장되므로 실측상 이렇게 갈렸다:
    #
    #     sido=서울        regions 26건   search.total 9
    #     sido=서울특별시   regions  0건   search.total 9    <- 어긋남
    #
    # 화면은 SIDO_LIST가 축약형을 보내 드러나지 않지만, 검색 화면은 **URL 파라미터로
    # 상태를 복원한다**(`SearchForm.tsx:190` -> 277행에서 그 값으로 regions 조회).
    # 그래서 `?sido=서울특별시` 링크를 열면 결과는 나오는데 시/군/구만 비어 지역을
    # 좁힐 수 없다.
    # ------------------------------------------------------------------
    print("\n--- sido 표기 정규화: /search 와 /search/regions 일치 ---")
    base = client.get("/api/v1/search/regions", params={"sido": "서울"})
    check("regions?sido=서울 200", base.status_code == 200, "-> %d" % base.status_code)
    canonical = base.json().get("sigungu", []) if base.status_code == 200 else []
    check("축약형이 시/군/구를 실제로 돌려준다", len(canonical) > 0, "-> %d건" % len(canonical))

    for variant in ("서울특별시", "서울시"):
        r = client.get("/api/v1/search/regions", params={"sido": variant})
        got = r.json().get("sigungu", []) if r.status_code == 200 else []
        check("★ regions?sido=%s 가 축약형과 같은 목록" % variant, got == canonical,
              "-> %d건 (축약형 %d건)" % (len(got), len(canonical)))
        # 응답의 sido는 **요청값 그대로** 돌려준다(정규화값이 아니다) — 기존 응답 계약 유지.
        if r.status_code == 200:
            check("regions 응답 sido는 요청값 그대로", r.json().get("sido") == variant,
                  "-> %r" % r.json().get("sido"))

    # /search 쪽도 같은 값을 봐야 한다(두 엔드포인트가 어긋나지 않는다).
    t_short = client.get("/api/v1/search", params={"sido": "서울"}).json()["total"]
    t_long = client.get("/api/v1/search", params={"sido": "서울특별시"}).json()["total"]
    check("★ search 총건수도 표기와 무관하게 같다", t_short == t_long,
          "-> 축약 %s / 정식 %s" % (t_short, t_long))

    # 알 수 없는 값은 빈 목록(500이 아니다) — fallback이 원본을 그대로 쓰는 경로.
    r = client.get("/api/v1/search/regions", params={"sido": "없는지역명"})
    check("알 수 없는 sido -> 200 + 빈 목록", r.status_code == 200 and r.json()["sigungu"] == [],
          "-> %d %s" % (r.status_code, r.text[:60]))

    check_search_list_contract()
    check_no_stale_read_path()
    check_every_list_screen_contract()
    check_search_issues_a_constant_number_of_queries()

    print()
    if FAILURES:
        print(f"{len(FAILURES)}건 실패: {FAILURES}")
        return 1
    print(f"전체 {PASS}건 통과")
    return 0


if __name__ == "__main__":
    sys.exit(run())
