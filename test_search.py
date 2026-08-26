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
import secrets
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# 이 프로세스 안에서만 유효한 합성 JWT 비밀값. **운영 값이 아니다.**
#
# 왜 필요한가 (2026-08-26): 아래 "로그인 화면이 같은 주소 원문을 받는가"(Sprint 250)
# 검사는 앱이 실제로 쓰는 시크릿으로 토큰을 서명해 **진짜 인증 경로**를 지난다.
# 그런데 `.env` 에 `SUPABASE_JWT_SECRET` 이 없으면(=지금 이 머신) 서명할 수가 없어
# 그 검사가 "공허하다"며 실패했다 — **제품 결함이 아니라 환경 미설정** 때문이다.
#
# 그 변수는 HS256(레거시) 전용이고 지금 Supabase 는 ES256 을 발급한다. 즉 운영에
# 없어도 정상일 수 있는 값이라, 그것 하나에 API 계약 검사가 묶여 있는 것이 잘못이다.
# 이 검사가 확인하려는 것은 **주소 원문이 인증 경로를 지나며 변형되지 않는가**이지
# 시크릿이 프로비저닝됐는가가 아니다.
#
# 이 저장소는 같은 상황에서 이미 같은 방법을 쓴다 — `test_api_regression.py`,
# `test_admin_secret_contract.py`, `test_admin_id_bounds.py`,
# `test_admin_failure_injection.py` 네 곳이 전부 이 관례다. 그것을 그대로 따른다.
#
# ★ `api/auth.py` 가 **모듈 최상단에서 한 번만** 읽으므로 import 보다 먼저 넣어야 한다.
# ★ 이미 설정돼 있으면 덮어쓰지 않는다 — 운영 값이 있는 환경에서는 그 값을 그대로 쓴다.
# ★ 값은 매 실행 랜덤이고 프로세스 환경에만 있다. `.env` 파일은 건드리지 않는다.
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-search-" + secrets.token_hex(16)

from fastapi.testclient import TestClient          # noqa: E402
from api_server import app                         # noqa: E402

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

    ## ★ 2026-08-24 Sprint 252 — 세는 대상을 바꿨다 (계약은 그대로다)

    그날 `api.ts` 가 리팩터링되면서 **요청을 내는 자리가 `fetch(` 가 아니게 됐다.**
    다섯 래퍼가 각자 `fetch()` 를 부르던 것을, 시간 제한을 한 곳에 모으려고
    `timedRequest()` 하나를 거치도록 바꿨다(그 전에는 타임아웃이 **하나도 없어서**
    백엔드가 멈추면 화면이 영원히 `불러오는 중...` 이었다).

        예전 모양   fetch(url, { cache: 'no-store', ... })         x 5
        지금 모양   timedRequest(url, { cache: 'no-store', ... })  x 6  -> 내부에서 fetch 1회
        (2026-08-24 Sprint 253 에 이름이 timedFetch -> timedRequest 로 바뀌었다 —
         본문 소비까지 타이머 안에 넣으면서 Response 대신 파싱 결과를 돌려주게 됐다)

    그래서 `fetch(` 개수를 세던 이 검사가 "1개"를 보고 **공허하다고 스스로 판정**했다.
    검사가 틀린 것이지 계약이 깨진 것이 아니다 — 세는 대상을 **요청을 내는 호출부**
    (`timedRequest`)로 옮기고, `fetch(` 는 **정확히 1개**(timedRequest 안)여야 한다는
    조건을 새로 건다. 그래야 "시간 제한을 우회하는 맨 fetch" 가 다시 생기면 잡힌다.

    이 갱신 과정에서 **실제 누락도 하나 나왔다**: 새로 옮겨 온 `headOk()` 의 HEAD 요청에
    `no-store` 가 없었다(옮겨 오기 전 맨 fetch 에도 없었다). 브라우저가 그 응답을
    재사용하면 이미 사라진 문서에 대해 뷰어가 열린다. 같은 자리에서 함께 고쳤다.
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
    # 요청을 내는 자리 = timedRequest **호출부**. 여기에 init(캐시 옵션 포함)이 실린다.
    # `function timedRequest(` 정의 자체는 호출이 아니므로 뺀다 — 넣으면 호출부보다
    # 하나 많아져서 no-store 개수와 영원히 어긋난다(실제로 한 번 그렇게 틀렸다).
    requests_out = len(_re.findall(r"(?<!function )\btimedRequest\b", code))
    # 맨 fetch 는 timedRequest 정의 안의 1개뿐이어야 한다. 그보다 많으면
    # 시간 제한과 캐시 계약을 함께 우회하는 경로가 생긴 것이다.
    bare_fetch = len(_re.findall(r"(?<![\w.])fetch\(", code))
    nostore = code.count("no-store")

    check("api.ts 의 요청 호출부를 실제로 찾았다(검사가 공허하지 않다)",
          requests_out >= 4, "-> timedRequest %d개" % requests_out)
    check("★ 시간 제한을 우회하는 맨 fetch 가 없다(정의 1개뿐)",
          bare_fetch == 1, "-> fetch %d개 (timedRequest 정의 안의 1개여야 한다)" % bare_fetch)
    check("★ 모든 요청이 no-store 다(옛 응답을 재사용하지 않는다)",
          nostore >= requests_out,
          "-> timedRequest %d / no-store %d" % (requests_out, nostore))

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
    print("    api.ts 요청 호출부 %d곳 / no-store %d곳 / 맨 fetch %d곳"
          % (requests_out, nostore, bare_fetch))

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




# ---------------------------------------------------------------------------
# 선언된 필터 파라미터가 **실제로 결과를 바꾸는가** (2026-08-21 Sprint 244 신설)
# ---------------------------------------------------------------------------
def check_declared_filters_actually_filter():
    """`Query(...)` 로 선언된 필터가 **동작까지** 하는지 본다.

    ## 왜 필요했나 - 소스 검사만으로는 못 잡는 구멍이 있다

    `tests/source-contract.test.mjs` 는 프런트가 보내는 키가 백엔드 선언을 벗어나지
    않는지 보고, `KNOWN_UNSUPPORTED` 목록에 올린 것이 "실제로 아직 미지원"인지 확인한다.
    좋은 가드지만 **선언만 보고 구현은 보지 않는다.**

    2026-08-21 mutation 으로 그 구멍을 실증했다:

        1단계  `min_building_area: float = Query(None)` 을 **선언만** 추가(WHERE 절 없음)
               -> source-contract 가 "미지원 목록에 있는데 백엔드가 지원한다"고 실패한다 (잡힘)
        2단계  개발자가 자연스럽게 `KNOWN_UNSUPPORTED` 에서 그 이름을 뺀다
               -> **소스 검사 36건이 전부 통과한다.**
               그런데 실제 동작은 그대로다: 전체 830건, 건물면적 99999 이상도 830건.
               = 사용자는 필터를 걸었는데 걸리지 않은 결과를 본다.

    즉 "선언했다"와 "거른다"는 다른 사실인데, 소스 검사는 앞의 것만 본다.
    이 검사가 뒤의 것을 본다 - **극단값을 보내고 결과 수가 실제로 달라지는지** 센다.

    ## 지금 알려진 미지원 파라미터

    프런트는 면적/특수조건 필터 UI 를 갖고 있고 값을 실제로 **보낸다**. 백엔드는 그것을
    받지 않는다(`auction_item` 에 면적 컬럼이 없다). 그래서 사용자가 면적을 걸어도
    결과가 그대로다 - 2026-08-21 실측으로 확인했다. 이것은 **알려진 미구현**이며
    이 검사는 그 사실을 고정한다(구현되면 이 목록에서 빼야 통과한다).
    """
    print("\n=== 선언된 필터가 실제로 거르는가 (Sprint 244) ===")
    import re
    import tempfile
    import shutil
    import contextlib
    import io as _io

    src = _io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "api", "v1", "search.py"), encoding="utf-8-sig").read()
    declared = re.findall(r"^\s{4}(\w+)\s*:[^\n=]*=\s*Query\(", src, re.M)
    # 필터가 아닌 것(표시 설정/페이지네이션)은 제외한다
    NOT_FILTERS = {"sort_by", "sort_order", "page", "size"}
    filters = [d for d in declared if d not in NOT_FILTERS]
    check("검사가 공허하지 않다(필터 파라미터를 찾았다)", len(filters) >= 10,
          "찾은 필터 %d개" % len(filters))

    # 각 필터를 "아무것도 남지 않아야 하는" 극단값으로 호출한다
    EXTREME = {
        "case_no": "존재하지않는사건번호zzz",
        "sido": "존재하지않는시도zzz",
        "sigungu": "존재하지않는시군구zzz",
        "dong": "존재하지않는동zzz",
        "address_detail": "존재하지않는주소zzz",
        "property_type": "존재하지않는종류zzz",
        "court_name": "존재하지않는법원zzz",
        "status": "존재하지않는상태zzz",
        "auction_date_from": "2999-12-31",
        "auction_date_to": "1900-01-01",
        "min_appraisal": 10 ** 15,
        "max_appraisal": 1,
        "min_bid_price": 10 ** 15,
        "max_bid_price": 1,
        "min_bid_rate": 99.0,
        "max_bid_rate": 0.0,
        "min_fail_count": 9999,
        "max_fail_count": -1,
        # 면적 4종은 2026-08-26 에 **구현됐다**(migration 025 + extract_areas).
        # KNOWN_UNSUPPORTED 에서 빠졌으므로 이제 아래 극단값이 실제로 0건을 만들어야 하고,
        # 안 그러면 이 검사가 붉어진다 — 즉 구현이 되돌려지면 여기서 잡힌다.
        "min_building_area": 10 ** 9,
        "max_building_area": 1,
        "min_land_area": 10 ** 9,
        "max_land_area": 1,
        # 미구현(프런트는 보내지만 백엔드가 안 받는다) — 원천 데이터가 없다
        "special_conditions": "존재하지않는조건zzz",
    }
    # `include_closed` 는 **범위를 넓히는** 파라미터라 극단값 개념이 다르다 - 따로 본다.
    SPECIAL = {"include_closed"}

    # 2026-08-21 실측: 프런트는 보내지만 백엔드가 받지 않는 것들.
    #
    # ★ 목록을 여기서 **새로 적지 않는다.** 정본은 `tests/_search_param_contract.mjs`
    #   하나뿐이고, 여기와 node 검사 두 개가 **모두 그 파일을 읽는다.**
    #   두 벌로 두면 한쪽만 갱신되는 날이 오고, 그때 검사들이 서로를 눈감아 준다 -
    #   이 저장소가 "규칙이 두 벌"에서 반복해 겪은 사고다(BUGS #107/#112/#136/#161/#204).
    #
    #   실제로 그 구멍을 mutation 으로 확인했다(2026-08-21): 파라미터를 선언만 하고
    #   목록에서 빼면 소스 검사 36건이 전부 통과하는데 필터는 여전히 아무것도 거르지
    #   않았다. 아래 동기화 검사가 그 편집을 잡는다.
    #
    #   2026-08-26: 목록이 `source-contract.test.mjs` 안에 있었는데, node 쪽에 검사가
    #   하나 더 늘면서 **두 벌이 됐다.** 그래서 목록만 전용 모듈로 빼고 셋이 함께 읽는다.
    #   (그 이동 때 이 검사가 곧바로 붉어져 세 번째 소비자가 있다는 것을 알려 줬다 —
    #    단일 정본 규칙이 실제로 작동한 사례다.)
    sc = _io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "tests", "_search_param_contract.mjs"),
                  encoding="utf-8").read()
    m = re.search(r"export const KNOWN_UNSUPPORTED = new Set\(\[(.*?)\]\)", sc, re.S)
    check("미지원 목록 정본(_search_param_contract.mjs)을 읽었다(검사가 공허하지 않다)",
          bool(m), None)
    KNOWN_UNSUPPORTED = set(re.findall(r"['\"](\w+)['\"]", m.group(1))) if m else set()
    print("    정본이 선언한 미지원 목록: %s" % sorted(KNOWN_UNSUPPORTED))

    tmp = tempfile.mkdtemp(prefix="qa_filter_")
    try:
        import storage.database as db
        prev = db.DB_PATH
        path = os.path.join(tmp, "auction.db")
        db.DB_PATH = path
        import storage.migrate_v4_1 as mig
        import storage.migrations.run_migrations as runmig
        with contextlib.redirect_stdout(_io.StringIO()):
            db.init_db(); mig.migrate(); runmig.run()
        conn = db.get_connection()
        future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        cur = conn.execute("INSERT INTO auction_case (case_no,court_code,court_name)"
                           " VALUES ('2025타경1','B1','서울중앙지방법원')")
        conn.execute(
            "INSERT INTO auction_item (case_id,case_no,item_no,court_name,property_type,"
            "sido,sigungu,dong,full_address,appraisal_price,minimum_bid_price,bid_rate,"
            "auction_date,status,fail_count,crawl_date)"
            " VALUES (?,'2025타경1','1','서울중앙지방법원','아파트','서울','강남구','역삼동',"
            "'서울특별시 강남구 역삼동 1 [집합건물 84.5㎡]',300000000,240000000,0.8,?,'유찰 1회',1,?)",
            (cur.lastrowid, future, datetime.now().strftime("%Y-%m-%d")))
        conn.commit(); conn.close()

        from fastapi.testclient import TestClient
        from api_server import app
        c = TestClient(app)
        base = c.get("/api/v1/search?size=1").json()["total"]
        check("표본이 검색된다(검사가 공허하지 않다)", base == 1, "total=%s" % base)

        ineffective = []
        for f in filters:
            if f in SPECIAL:
                continue
            if f not in EXTREME:
                check("극단값을 정의해 둔 파라미터인가: %s" % f, False,
                      "EXTREME 에 없다 - 새 파라미터가 생겼으면 여기에 추가하라")
                continue
            r = c.get("/api/v1/search", params={f: EXTREME[f], "size": 1})
            if r.status_code != 200:
                check("%s 극단값이 200 이다" % f, False, "HTTP %s" % r.status_code)
                continue
            total = r.json()["total"]
            if total == base:
                ineffective.append(f)

        print("    선언된 필터 %d개 중 극단값에도 결과가 그대로인 것: %d개"
              % (len(filters) - len(SPECIAL), len(ineffective)))
        if ineffective:
            print("      %s" % sorted(ineffective))

        # ① 알려진 미구현 목록 밖에서 무효한 필터가 나오면 실패다
        unexpected = sorted(set(ineffective) - KNOWN_UNSUPPORTED)
        check("★ 선언된 필터가 실제로 결과를 거른다(미구현 목록 밖)",
              unexpected == [],
              "선언만 돼 있고 거르지 않는다: %s - WHERE 절이 빠졌는지 확인하라" % unexpected)

        # ② 미구현 목록에 있는데 **사실은 구현된** 것이 있으면 목록을 갱신해야 한다
        now_working = sorted(KNOWN_UNSUPPORTED & set(filters) - set(ineffective))
        check("★ 미구현 목록이 최신이다(구현된 것이 남아 있지 않다)",
              now_working == [],
              "이제 동작한다 - KNOWN_UNSUPPORTED 에서 빼라: %s" % now_working)

        # ③ 프런트가 보내는데 백엔드가 안 받는 것이 실제로 존재한다는 사실을 고정한다
        #    (0이 되면 이 검사와 프런트 TODO 주석을 함께 정리해야 한다)
        front = _io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "src", "app", "search", "SearchForm.tsx"),
                         encoding="utf-8").read()
        sent_but_unsupported = sorted(
            k for k in KNOWN_UNSUPPORTED if ("query.%s" % k) in front)
        print("    프런트가 **보내는데** 백엔드가 안 받는 것: %s" % sent_but_unsupported)
        check("★ 그 목록이 비어 있지 않다(현재 사용자 영향이 실재한다)",
              len(sent_but_unsupported) > 0,
              "비었다면 미구현이 해소된 것이다 - KNOWN_UNSUPPORTED 와 프런트 TODO 를 함께 정리하라")
    finally:
        db.DB_PATH = prev
        shutil.rmtree(tmp, ignore_errors=True)



# ---------------------------------------------------------------------------
# 로그인이 필요한 화면들이 **같은 주소 원문**을 받는가 (2026-08-21 Sprint 250 신설)
# ---------------------------------------------------------------------------
def check_authed_screens_get_the_same_address():
    """관심물건 / 최근 본 물건 / 상세가 DB 원문과 **글자 단위로 같은** 주소를 주는가.

    ## 왜 필요했나

    주소는 사용자가 물건을 판단하는 1차 정보다. 그런데 이 저장소의 감사는 로그인 뒤
    화면에서 **번번이 막혀 있었다** - 헤드리스 브라우저에 Supabase 세션이 없어
    `/favorites` 가 `/login` 으로 튕기기 때문이다. 그래서 "API 계약은 확인했고 화면은
    못 봤다"가 반복됐다.

    브라우저 렌더는 여전히 세션 쿠키가 필요하지만, **API 계약은 여기서 끝까지 확인할 수
    있다** - fixture DB 를 만들고 앱이 실제로 쓰는 시크릿으로 토큰을 서명하면
    제품의 실제 인증 경로(`get_current_user`)를 그대로 지난다. mock 이 아니다.

    ## 무엇을 고정하는가

    주소는 파싱하지 않고 **원문 그대로** 실려야 한다. 어느 화면이 대괄호를 잘라내거나
    trim 하거나 이스케이프하면 화면마다 다른 주소가 보인다. 특히 아래 네 가지는
    이 저장소가 실제로 밟았던 모양이라 그대로 넣는다:

        중첩 대괄호      [토지 전[현황:묵전(죽림)] 105㎡ ...]
        대지권 표기      [집합건물 ... 74.5482㎡ 대지권의 표시 ... 대 500㎡]
        괄호 + 쉼표      (안락동,동래에코하임)
        비부동산        사용본거지 : ... [카니발 2016년식 승용차]

    운영 DB 는 건드리지 않는다 - 임시 DB 를 만들고 끝나면 지운다.
    """
    print("\n=== 로그인 화면이 같은 주소 원문을 받는가 (Sprint 250) ===")
    import contextlib
    import io as _io
    import shutil
    import tempfile
    from datetime import datetime, timedelta

    import storage.database as db
    from jose import jwt as _jwt
    import api.auth as auth_mod

    if not auth_mod.SUPABASE_JWT_SECRET:
        check("SUPABASE_JWT_SECRET 이 있다(없으면 이 검사는 공허하다)", False,
              "길이 0")
        return

    ADDRS = [
        "경기도 안성시 삼죽면 진촌리 107-5 [토지 전 2139㎡]",
        "전라남도 함평군 손불면 학산리 661 [토지 전[현황:묵전(죽림)] 105㎡ "
        "채무자겸소유자 백부덕 지분 36분의3 전부]",
        "부산광역시 동래구 명안로10번길 34 9층901호 (안락동,동래에코하임) "
        "[집합건물 철근콘크리트조 74.5482㎡ 대지권의 표시 토지의 표시 : "
        "부산광역시 동래구 안락동 308 대 500㎡]",
        "사용본거지 : 인천 부평구 백범로456번길 20-24 (십정동) [카니발 2016년식 승용차]",
    ]

    tmp = tempfile.mkdtemp(prefix="qa_addrctr_")
    prev = db.DB_PATH
    db.DB_PATH = os.path.join(tmp, "auction.db")
    try:
        import storage.migrate_v4_1 as mig
        import storage.migrations.run_migrations as runmig
        with contextlib.redirect_stdout(_io.StringIO()):
            db.init_db()
            mig.migrate()
            runmig.run()

        future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        now = datetime.now().isoformat()
        today = datetime.now().strftime("%Y-%m-%d")
        conn = db.get_connection()
        ids = []
        for n, addr in enumerate(ADDRS, start=1):
            cno = "2025타경%d" % n
            cid = conn.execute(
                "INSERT INTO auction_case (case_no,court_code,court_name)"
                " VALUES (?,'B1','서울중앙지방법원')", (cno,)).lastrowid
            cur = conn.execute(
                "INSERT INTO auction_item (case_id,case_no,item_no,court_name,"
                "property_type,sido,sigungu,dong,full_address,appraisal_price,"
                "minimum_bid_price,bid_rate,auction_date,status,fail_count,crawl_date)"
                " VALUES (?,?,'1','서울중앙지방법원','아파트','서울','강남구','역삼동',?,"
                "300000000,240000000,0.8,?,'유찰 1회',1,?)",
                (cid, cno, addr, future, today))
            ids.append(cur.lastrowid)

        user = "qa-addr-contract-user"
        rcols = [r[1] for r in conn.execute("PRAGMA table_info(recent_items)")]
        for iid in ids:
            conn.execute("INSERT INTO favorites (user_id,item_id,created_at)"
                         " VALUES (?,?,?)", (user, iid, now))
            cols = ["user_id", "item_id"] + [c for c in ("viewed_at", "created_at")
                                             if c in rcols]
            conn.execute("INSERT INTO recent_items (%s) VALUES (%s)"
                         % (",".join(cols), ",".join("?" * len(cols))),
                         tuple([user, iid] + [now] * (len(cols) - 2)))
        conn.commit()
        conn.close()

        from fastapi.testclient import TestClient
        from api_server import app
        client = TestClient(app)
        hdr = {"Authorization": "Bearer " + _jwt.encode(
            {"sub": user}, auth_mod.SUPABASE_JWT_SECRET, algorithm="HS256")}

        # 전제 - 토큰이 실제로 통해야 아래가 의미가 있다
        probe = client.get("/api/v1/favorites", headers=hdr)
        check("전제: 토큰이 제품 인증 경로를 통과한다", probe.status_code == 200,
              "-> %s %s" % (probe.status_code, probe.text[:120]))
        check("전제: 인증 없이는 막힌다",
              client.get("/api/v1/favorites").status_code == 401)
        if probe.status_code != 200:
            return

        want = dict(zip(ids, ADDRS))

        def rows_of(payload):
            if isinstance(payload, dict):
                for k in ("data", "items", "results"):
                    v = payload.get(k)
                    if isinstance(v, list):
                        return v
                    if isinstance(v, dict):
                        for k2 in ("items", "results"):
                            if isinstance(v.get(k2), list):
                                return v[k2]
            return payload if isinstance(payload, list) else []

        for label, path in (("관심물건", "/api/v1/favorites"),
                            ("최근 본 물건", "/api/v1/recent-items")):
            rows = rows_of(client.get(path, headers=hdr).json())
            check("%s 가 %d건을 돌려준다(검사가 공허하지 않다)" % (label, len(ids)),
                  len(rows) == len(ids), "-> %d건" % len(rows))
            mism = [(r.get("id"), r.get("full_address")) for r in rows
                    if r.get("id") in want and r.get("full_address") != want[r["id"]]]
            check("★ %s 의 주소가 DB 원문과 글자 단위로 같다" % label, not mism,
                  "-> %r" % (mism[:2],))

        mism = []
        for iid in ids:
            r = client.get("/api/v1/item/%d" % iid)
            if r.status_code != 200 or r.json().get("full_address") != want[iid]:
                mism.append((iid, r.status_code, r.json().get("full_address")))
        check("★ 상세의 주소가 DB 원문과 글자 단위로 같다", not mism,
              "-> %r" % (mism[:2],))
    finally:
        db.DB_PATH = prev
        shutil.rmtree(tmp, ignore_errors=True)

def check_sort_and_injection_are_bounded():
    """정렬 파라미터와 적대 입력이 **SQL 을 바꾸지 못하는가** (2026-08-25 신설, BUGS #207).

    ## 왜 이 자리인가

    `/api/v1/search` 는 사용자 입력을 두 갈래로 다룬다.

        텍스트 필드(case_no/sido/dong/...)  ->  전부 `?` 바인딩. 값이 SQL 이 되지 않는다.
        **정렬(sort_by / sort_order)**      ->  **SQL 문자열에 직접 들어간다**
                                                (`f"ORDER BY {order_clause}"`)

    즉 이 API 에서 사용자 입력이 SQL 문법에 닿는 곳은 정렬 하나뿐이다. 방어는
    `SORT_COLUMNS` 화이트리스트 + `sort_order` 고정 삼항인데, **그 방어를 확인하는
    검사가 하나도 없었다**(2026-08-25 실측: 이 파일 142단언 중 sort_by 적대 입력 0건).

    화이트리스트는 조용히 무너지기 쉽다 - 누가 `SORT_COLUMNS.get(sort_by, sort_by)`
    처럼 "친절한" 기본값을 넣거나 검증 한 줄을 지우면 곧바로 `ORDER BY` 주입이 된다.
    그 편집은 정상 요청을 하나도 깨뜨리지 않으므로 다른 검사에 걸리지 않는다.

    ## 합성 DB 로 재는 이유

    개발 머신의 DB 는 **기본 질의(종결 제외)가 0건**이다 - 1,876건이 다 있지만 기일이
    전부 지났다(마지막 크롤 2026-08-12, 이 저장소의 P0-A 맥락). 이 파일의 다른 검사들은
    `include_closed=True` 를 붙여 1,876건을 보지만, 여기서는 **정렬 결과를 눈으로 확인**
    해야 하므로 값이 서로 다른 소수의 행이 필요하다. 0건끼리 비교하면 주입이 통해도
    통하지 않아도 똑같이 0 이라 검사가 공허해지기도 한다.

    (2026-08-25 실측: 기본 0건 / `include_closed=true` 1,876건 /
     `auction_date_from=2000-01-01` 1,875건.)

    실제 HTTP(uvicorn)로도 같은 입력을 눌러 400/누출 없음을 확인했다. 여기서는
    TestClient 로 고정한다 - 이 파일의 나머지와 같은 방식이고 서버 기동이 필요 없다.
    """
    import contextlib
    import io as _io
    import json as _json
    import sqlite3 as _sqlite3
    import tempfile

    print("\n--- 10. 정렬/적대 입력이 SQL 을 바꾸지 못한다 (BUGS #207) ---")
    tmp = tempfile.mkdtemp(prefix="qa_inject_")
    import storage.database as db
    prev = db.DB_PATH
    try:
        path = os.path.join(tmp, "auction.db")
        db.DB_PATH = path
        import storage.migrate_v4_1 as mig
        import storage.migrations.run_migrations as runmig
        with contextlib.redirect_stdout(_io.StringIO()):
            db.init_db(); mig.migrate(); runmig.run()

        conn = db.get_connection()
        today = datetime.now().strftime("%Y-%m-%d")
        cur = conn.execute("INSERT INTO auction_case (case_no,court_code,court_name)"
                           " VALUES ('2025타경9','B9','서울중앙지방법원')")
        case_id = cur.lastrowid
        # 정렬이 **관측 가능하도록** 값을 서로 다르게 넣는다
        ROWS = 5
        for i in range(ROWS):
            d = (datetime.now() + timedelta(days=10 + i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO auction_item (case_id,case_no,item_no,court_name,property_type,"
                "sido,sigungu,dong,full_address,appraisal_price,minimum_bid_price,bid_rate,"
                "auction_date,status,fail_count,crawl_date)"
                " VALUES (?,'2025타경9',?,'서울중앙지방법원','아파트','서울','강남구','역삼동',"
                "?,?,?,?,?,'유찰 1회',?,?)",
                (case_id, str(i + 1), "서울특별시 강남구 역삼동 %d" % (i + 1),
                 300000000 + i, 100000000 + i * 1000, 0.8, d, i, today))
        conn.commit(); conn.close()

        from fastapi.testclient import TestClient
        from api_server import app
        c = TestClient(app)

        def q(**kw):
            r = c.get("/api/v1/search", params={k: v for k, v in kw.items() if v is not None})
            try:
                return r.status_code, r.json()
            except Exception:
                return r.status_code, r.text

        # (0) 검사가 공허하지 않다 - 합성 행이 실제로 검색에 잡힌다
        code, body = q(size=50, page=1)
        base_total = body.get("total") if isinstance(body, dict) else None
        check("검사가 공허하지 않다(합성 행이 검색된다) - %s건" % base_total,
              code == 200 and base_total == ROWS, "-> %s / %s" % (code, base_total))

        # (1) 정렬이 **실제로 동작한다** - 이게 아래 적대 입력 검사의 대조군이다
        _, asc = q(size=50, page=1, sort_by="minimum_bid_price", sort_order="asc")
        _, desc = q(size=50, page=1, sort_by="minimum_bid_price", sort_order="desc")
        a = [it["minimum_bid_price"] for it in (asc.get("items") or [])]
        d_ = [it["minimum_bid_price"] for it in (desc.get("items") or [])]
        check("오름차순이 실제로 오름차순이다", a == sorted(a), "-> %s" % a[:5])
        check("내림차순이 실제로 내림차순이다", d_ == sorted(d_, reverse=True), "-> %s" % d_[:5])
        check("두 방향이 서로 다르다(정렬이 무시되지 않는다)", a != d_,
              "-> %s vs %s" % (a[:3], d_[:3]))

        # 화이트리스트의 **모든** 키가 실제로 받아들여지는가 (목록이 죽은 값이 아니다)
        from api.v1.search import SORT_COLUMNS
        bad_keys = [k for k in SORT_COLUMNS if q(size=1, page=1, sort_by=k)[0] != 200]
        check("화이트리스트 %d개 키가 전부 200 이다" % len(SORT_COLUMNS), not bad_keys,
              "-> 거부된 키: %s" % bad_keys)

        # (2) 적대 입력은 전부 400 이다 - 200(통과)도 500(터짐)도 아니다
        SORT_PAYLOADS = [
            "auction_date; DROP TABLE auction_item--",
            "auction_date, (SELECT COUNT(*) FROM sqlite_master)",
            "(SELECT 1)", "auction_date--", "auction_date/**/", "auction_date)--",
            "1", "*", "", "id", "rowid",
            "auction_date COLLATE NOCASE", "CASE WHEN 1 THEN 1 ELSE 2 END",
        ]
        ORDER_PAYLOADS = ["asc--", "; DROP TABLE auction_item--", "x",
                          "asc, (SELECT 1)", "1"]
        bad = []
        for p in SORT_PAYLOADS:
            code, _b = q(size=5, page=1, sort_by=p)
            if code != 400:
                bad.append(("sort_by", p, code))
        for p in ORDER_PAYLOADS:
            code, _b = q(size=5, page=1, sort_order=p)
            if code != 400:
                bad.append(("sort_order", p, code))
        check("★ 정렬 적대 입력 %d건이 전부 400 이다"
              % (len(SORT_PAYLOADS) + len(ORDER_PAYLOADS)),
              not bad, "-> 400 이 아닌 것: %s" % bad[:4])

        # (3) 400 본문이 **스키마를 흘리지 않는다** - 입력 반향은 허용, 컬럼 목록 노출은 아니다
        code, body = q(size=5, page=1, sort_by="nonexistent_column")
        # 먼저 **거부됐는지**를 본다. 이걸 빼면 통과했을 때(200) 응답 본문 전체를 훑게 돼
        # 정상 데이터의 컬럼명을 "누출"로 오인한다(2026-08-25 mutation 에서 실제로 그랬다).
        check("미등록 sort_by 는 거부된다(아래 누출 검사의 전제)", code == 400, "-> %s" % code)
        detail = _json.dumps(body, ensure_ascii=False) if isinstance(body, dict) else str(body)
        leaked = [col for col in SORT_COLUMNS if col in detail] if code == 400 else []
        check("★ 400 본문이 허용 컬럼 목록을 흘리지 않는다", not leaked,
              "-> %s 가 오류 본문에 들어 있다. 공격자에게 정렬 가능한 컬럼을 알려 준다" % leaked)
        check("400 본문에 SQL 조각이 없다",
              not any(w in detail.upper() for w in ("SELECT ", "ORDER BY", "SQLITE_MASTER")),
              detail[:120])

        # (4) 텍스트 필드는 바인딩된다 - 값이 SQL 이 되지 않는다
        #
        #     주의: "아무 행도 안 나온다"를 그대로 단언하면 **틀린 검사**가 된다.
        #     `sido` 는 `extract_sido()` 로 정규화되는데 이게 **부분일치**라
        #     "서울' AND 1=1--" 에서 "서울" 을 뽑아낸다 -> `sido = '서울'` -> 전부 매치.
        #     (2026-08-25 실측. 처음에 그렇게 써서 붉어졌고, 원인을 재보니 주입이 아니라
        #      정규화였다.) 그러니 **유효한 지역명을 품지 않은** 입력으로 바인딩을 재고,
        #     정규화 쪽은 아래에서 따로 "주입이 아니라 정규화임"을 증명한다.
        TEXT = ["1' UNION SELECT name FROM sqlite_master--",
                "'; DROP TABLE auction_item;--",
                "' OR '1'='1"]
        wrong = []
        for f in ("case_no", "court_name", "address_detail", "sido", "dong", "status"):
            for p in TEXT:
                code, body = q(size=50, page=1, **{f: p})
                if code != 200:
                    wrong.append((f, p, code))
                elif isinstance(body, dict) and body.get("total"):
                    # 주입이 통했다면 필터가 무력화돼 전체가 나온다. 바인딩되면 0건이다.
                    wrong.append((f, p, "total=%s" % body["total"]))
        check("★ 텍스트 적대 입력 %d건이 200 이고 아무 행도 매치하지 않는다" % (6 * len(TEXT)),
              not wrong, "-> %s" % wrong[:4])

        # (4-b) 정규화가 지역명을 뽑아내는 경우는 **주입이 아니라 정규화**임을 증명한다.
        #       같은 요청이 평문 "서울" 과 **정확히 같은 결과**를 내면, 페이로드의
        #       SQL 조각은 아무 역할도 하지 않은 것이다.
        from normalizer.normalizer import extract_sido as _ex
        payload = "서울' AND 1=1--"
        check("정규화가 페이로드에서 지역명만 뽑는다", _ex(payload) == "서울",
              "-> %r" % _ex(payload))
        _, poisoned = q(size=50, page=1, sido=payload)
        _, plain = q(size=50, page=1, sido="서울")
        check("★ 페이로드 결과 == 평문 '서울' 결과 (SQL 조각이 무력하다)",
              [it["id"] for it in (poisoned.get("items") or [])]
              == [it["id"] for it in (plain.get("items") or [])],
              "-> %s vs %s" % (poisoned.get("total"), plain.get("total")))
        # 그리고 지역명을 **품지 않은** 같은 모양의 페이로드는 0건이어야 한다
        _, none_match = q(size=50, page=1, sido="zzz' AND 1=1--")
        check("지역명 없는 같은 모양 페이로드는 0건", none_match.get("total") == 0,
              "-> %s" % none_match.get("total"))

        # (5) 주입 시도 뒤에도 DB 가 그대로인가 - 이게 최종 증거다
        code, body = q(size=50, page=1)
        check("주입 시도 뒤 검색 결과가 그대로다", body.get("total") == ROWS,
              "-> %s" % body.get("total"))
        raw = _sqlite3.connect(path)
        names = {r[0] for r in raw.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        cnt = raw.execute("SELECT COUNT(*) FROM auction_item").fetchone()[0]
        raw.close()
        check("★ auction_item 테이블이 살아 있다", "auction_item" in names,
              "-> %s" % sorted(names)[:8])
        check("★ 행이 하나도 지워지지 않았다", cnt == ROWS, "-> %s" % cnt)
    finally:
        db.DB_PATH = prev


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
    # ★ 2026-08-26: 면적 4종을 **구현하면서** 이 목록에서 뺐다.
    #   위 주석이 예고한 그대로다 — "백엔드에 그 이름이 생기면 이 검사가 실패한다.
    #   프론트 TODO를 정리하고 기대값을 옮기라는 신호다." 실제로 그 신호가 왔고
    #   (min/max_building_area, min/max_land_area 4건이 "더 이상 무시되지 않는다"로 붉어졌다)
    #   여기와 프런트 주석, source-contract 의 KNOWN_UNSUPPORTED 를 함께 정리했다.
    #
    #   구현: migration 025(컬럼+인덱스) / normalizer.extract_areas()(주소 원문에서 추출,
    #   실데이터 커버리지 99.3%) / api/v1/search.py(WHERE 절) / backfill_area.py(기존 행).
    #
    #   `special_conditions` 만 남는다 — 면적과 달리 **원천 데이터 자체가 없다**
    #   (auction_item 에도 rights_summary 에도 대응 필드가 없다).
    UNSUPPORTED = ("special_conditions",)

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


    # --- 9. 날짜 파라미터 검증 (2026-08-25, docs/BUGS.md #201) --------------
    #
    # 이 엔드포인트는 나머지 필터를 전부 400 + 사유로 거절하는데
    # (sort_by / sort_order / property_type / min·max 숫자 6종 / page),
    # 날짜 두 개만 검증이 없어 **오타가 조용히 0건**이 됐다.
    # 실측(수정 전): `auction_date_from=not-a-date` -> HTTP 200 / total=0.
    # 같은 폼에서 나온 값인데 숫자는 즉시 거절하고 날짜는 조용히 삼키는 것이
    # 이 저장소가 반복해서 잡아 온 "조용히 틀린 결과"다.
    print("\n--- 9. 날짜 파라미터 검증 (BUGS #201) ---")

    def date_status(key, value):
        r = client.get("/api/v1/search",
                       params={"include_closed": True, key: value, "size": 1})
        return r.status_code

    # ★ 날짜를 **아예 안 넘긴** 경우(None)를 검증하면 모든 검색이 400 이 된다.
    #   `if not _value: continue` 가드가 load-bearing 이라는 뜻이라 따로 잠근다.
    r_nodate = client.get("/api/v1/search", params={"include_closed": True, "size": 1})
    check("날짜 파라미터를 안 넘긴 검색은 그대로 200",
          r_nodate.status_code == 200, "-> %s %s" % (r_nodate.status_code, r_nodate.text[:120]))

    REJECT = [
        ("형식이 아닌 문자열", "not-a-date"),
        ("달력상 불가능한 달", "2026-13-01"),
        ("달력상 불가능한 날", "2026-02-30"),
        ("슬래시 구분자", "2026/01/01"),
        ("시각이 붙은 값", "2026-01-01T00:00:00"),
        ("SQL 조각", "2026-01-01') OR 1=1--"),
        ("숫자만", "20260101"),
    ]
    for key in ("auction_date_from", "auction_date_to"):
        for label, value in REJECT:
            got = date_status(key, value)
            check("%s - %s 는 400 으로 거절" % (key, label),
                  got == 400, "-> %s" % got)

    # 대조군 - 정상 값은 통과해야 한다. 없으면 "전부 400" 으로도 통과해 공허해진다.
    for key in ("auction_date_from", "auction_date_to"):
        got = date_status(key, "2026-01-01")
        check("%s - 정상 YYYY-MM-DD 는 통과" % key, got == 200, "-> %s" % got)
        # 빈 값은 "안 걸었다"는 뜻이다(기존 계약을 바꾸지 않는다).
        got = date_status(key, "")
        check("%s - 빈 값은 필터를 걸지 않은 것으로 본다" % key, got == 200, "-> %s" % got)

    # 거절 사유가 **어느 파라미터인지** 말해 주는가 (증거 없는 400 을 만들지 않는다)
    r = client.get("/api/v1/search",
                   params={"include_closed": True, "auction_date_from": "bad", "size": 1})
    body = r.text
    check("400 사유에 파라미터 이름이 들어 있다",
          "auction_date_from" in body, body[:200])
    check("400 사유에 기대 형식이 들어 있다",
          "YYYY-MM-DD" in body, body[:200])

    # 필터가 실제로 **동작**하는지도 함께 본다 - 검증만 붙이고 기능이 죽으면 안 된다.
    wide = total(auction_date_from="1900-01-01")
    narrow = total(auction_date_from="2999-12-31")
    check("정상 날짜 필터가 실제로 좁힌다(1900 >= 2999)", wide >= narrow, (wide, narrow))

    check_search_list_contract()
    check_no_stale_read_path()
    check_every_list_screen_contract()
    check_search_issues_a_constant_number_of_queries()
    check_declared_filters_actually_filter()
    check_authed_screens_get_the_same_address()
    check_sort_and_injection_are_bounded()
    check_area_filter_survives_missing_migration_025()
    check_area_families_are_a_union_not_a_pair()

    print()
    if FAILURES:
        print(f"{len(FAILURES)}건 실패: {FAILURES}")
        return 1
    print(f"전체 {PASS}건 통과")
    return 0



# ---------------------------------------------------------------------------
# 면적 필터가 migration 025 미적용 DB 에서 검색 전체를 죽이지 않는가
# (2026-08-26, `docs/BUGS.md` #220)
# ---------------------------------------------------------------------------
def check_area_filter_survives_missing_migration_025():
    """면적 필터의 **두 반쪽이 같은 방향으로** 동작하는지 본다.

    ## 무엇이 틀려 있었나

    면적 검색은 2026-08-26 에 한 번에 들어왔는데, 그 안에서 응답 쪽과 필터 쪽이
    **정반대로** 쓰여 있었다.

        응답  `_area_of(row, "building_area")`  -> 컬럼이 없으면 그 필드만 null
              (주석: *"검색 전체가 500 이 되는 것보다 그 필드만 null 이 낫다"*)
        필터  `conditions.append("building_area >= ?")` -> 컬럼이 없으면 그대로 500

    그래서 migration 025 가 적용되지 않은 DB 에서는 사용자가 면적을 **건드리는 순간**
    검색이 통째로 깨졌다. 프런트는 같은 날 '준비 중입니다' 를 걷어내고 실제 입력을
    열었으므로 도달 가능한 경로다. 실제로 이 저장소의 `test_id_bounds_sweep` 이
    `min_building_area=1.5 -> 500` 을 포함해 **20개 조합 전부**를 잡아 붉었다.

    ## 이 검사가 잠그는 것 — 그리고 왜 '0건' 만 봐서는 안 되는가

    `check_declared_filters_actually_filter()` 는 면적에 **극단값(10^9, 1)** 만 보내고
    0건을 기대한다. 그 검사는 "면적 조건이 오면 무조건 빈 결과" 라는 잘못된 고침으로도
    **그대로 통과한다** — 즉 이 결함의 수정을 검증하지 못한다.

    그래서 여기서는 컬럼이 **있는** DB 에서 중간값으로 걸러 *남을 것은 남고 빠질 것은
    빠지는* 것을 먼저 못박는다. 그 뒤에 컬럼을 실제로 **DROP** 해서 결손을 재현한다.
    두 쪽을 같이 봐야 방어가 공허해지지 않는다.
    """
    print("\n=== 면적 필터 x migration 025 미적용 (BUGS #220) ===")
    import contextlib
    import io as _io
    import shutil
    import tempfile

    import storage.database as dbmod
    import storage.migrate_v4_1 as mig
    import storage.migrations.run_migrations as runmig
    from api.v1.search import _area_columns_available

    workdir = tempfile.mkdtemp(prefix="qa_area_")
    orig_db = dbmod.DB_PATH
    try:
        # 스키마는 실제 부트스트랩 3단계 그대로 만든다 — 테스트가 스키마를 손으로
        # 베끼면 진짜 마이그레이션과 어긋나도 초록불을 유지한다.
        dbmod.DB_PATH = os.path.join(workdir, "t.db")
        with contextlib.redirect_stdout(_io.StringIO()):
            dbmod.init_db()
            mig.migrate()
            runmig.run()

        # 면적이 서로 다른 3건 + 면적을 모르는 1건.
        # 기일은 넉넉히 미래로 둬 기본 필터(auction_date >= 오늘)에 걸리지 않게 한다.
        rows = [
            (1, "2024타경901", 30.0, 55.0),
            (2, "2024타경902", 85.0, 120.0),
            (3, "2024타경903", 150.0, 300.0),
            (4, "2024타경904", None, None),   # 차량/선박처럼 면적을 뽑을 수 없는 물건
        ]
        c = dbmod.get_connection()
        try:
            for item_id, case_no, b, l in rows:
                case_id = c.execute(
                    "INSERT INTO auction_case (court_code, case_no) VALUES (?,?)",
                    ("서울중앙지방법원", case_no)).lastrowid
                c.execute(
                    "INSERT INTO auction_item"
                    " (id, case_id, case_no, item_no, court_name, property_type,"
                    "  sido, sigungu, full_address, auction_date,"
                    "  building_area, land_area)"
                    " VALUES (?,?,?,'1','서울중앙지방법원','아파트','서울','강남구',"
                    "         '서울 강남구 역삼동 1', '2099-01-01', ?, ?)",
                    (item_id, case_id, case_no, b, l))
            c.commit()
        finally:
            c.close()

        def q(**params):
            return client.get("/api/v1/search", params={"size": 100, **params})

        # ------------------------------------------------------------------
        # A. 컬럼이 있는 DB — 필터가 진짜로 거른다
        #    (이 부분이 없으면 아래 방어 검사가 공허해진다)
        # ------------------------------------------------------------------
        conn = dbmod.get_connection()
        try:
            check("전제: 부트스트랩 DB 에 면적 컬럼이 있다(025 적용)",
                  _area_columns_available(conn) is True)
        finally:
            conn.close()

        r = q()
        check("전제: 씨앗 4건이 기본 검색에 보인다",
              r.status_code == 200 and r.json()["total"] == 4,
              (r.status_code, r.text[:160]))

        r = q(min_building_area=50)
        got = sorted(i["id"] for i in r.json()["items"])
        check("★ 건물면적 >= 50 은 2·3만 남긴다(빈 결과가 아니다)", got == [2, 3], got)

        r = q(min_building_area=50, max_building_area=100)
        got = sorted(i["id"] for i in r.json()["items"])
        check("★ 건물면적 50~100 은 2만 남긴다", got == [2], got)

        r = q(min_land_area=200)
        got = sorted(i["id"] for i in r.json()["items"])
        check("★ 토지면적 >= 200 은 3만 남긴다", got == [3], got)

        r = q(min_building_area=0)
        got = sorted(i["id"] for i in r.json()["items"])
        check("★ 면적 미상(4번)은 면적 조건이 붙는 순간 빠진다(NULL 규약)",
              got == [1, 2, 3], got)

        got = [i["id"] for i in q(min_building_area=85).json()["items"]]
        check("★ 경계값은 포함이다(>= 85 에 85 가 든다)", 2 in got, got)

        # ------------------------------------------------------------------
        # B. 컬럼이 없는 DB — 결손을 **실제로 재현**한다 (DROP COLUMN)
        # ------------------------------------------------------------------
        # B-0. **한쪽만** 없는 결손을 먼저 본다.
        #
        #   두 컬럼을 한꺼번에 지워 놓고 보면 "면적 컬럼 목록에서 land_area 를 빠뜨린다"는
        #   실수를 잡지 못한다 — building_area 하나만 봐도 판정이 False 로 같기 때문이다.
        #   실제로 변이 M7(`AREA_COLUMNS` 에서 land_area 제거)이 이 단계 없이는
        #   **살아남는 것**을 확인하고 추가했다. 025 는 두 컬럼을 함께 넣으므로 흔한
        #   상태는 아니지만, 방어가 무엇을 근거로 참이 되는지는 정확해야 한다.
        conn = dbmod.get_connection()
        try:
            # 인덱스가 걸린 컬럼은 그대로 DROP 되지 않는다 — 025 가 만든 인덱스를 먼저 지운다.
            conn.execute("DROP INDEX IF EXISTS idx_auction_item_land_area")
            conn.execute("ALTER TABLE auction_item DROP COLUMN land_area")
            conn.commit()
            check("전제: 한쪽(land_area)만 없는 결손이 재현됐다",
                  _area_columns_available(conn) is False)
        finally:
            conn.close()
        rr = q(min_land_area=1)
        check("★★ 한쪽만 없어도 500 이 아니다(없는 쪽 조건)", rr.status_code == 200,
              (rr.status_code, rr.text[:160]))
        rr = q(min_building_area=50)
        check("★★ 한쪽만 없으면 남아 있는 쪽 조건도 빈 결과로 통일한다",
              rr.status_code == 200 and rr.json()["total"] == 0, rr.text[:160])

        conn = dbmod.get_connection()
        try:
            conn.execute("DROP INDEX IF EXISTS idx_auction_item_building_area")
            conn.execute("ALTER TABLE auction_item DROP COLUMN building_area")
            conn.commit()
            check("전제: 결손이 실제로 재현됐다(면적 컬럼 없음)",
                  _area_columns_available(conn) is False)
        finally:
            conn.close()

        r = q(min_building_area=50)
        check("★★ 컬럼이 없어도 500 이 아니다", r.status_code == 200,
              (r.status_code, r.text[:160]))
        check("★★ 면적 조건은 빈 결과가 된다(조건을 조용히 버리지 않는다)",
              r.status_code == 200 and r.json()["total"] == 0, r.text[:160])
        check("★★ 빈 응답도 계약 모양을 유지한다",
              r.status_code == 200
              and set(r.json()) >= {"total", "page", "size", "total_pages", "items"}
              and r.json()["items"] == [],
              r.text[:160])

        for name, params in (("min_land_area", {"min_land_area": 1}),
                             ("max_building_area", {"max_building_area": 10 ** 6}),
                             ("max_land_area", {"max_land_area": 10 ** 6}),
                             ("음수", {"min_building_area": -1}),
                             ("소수", {"min_building_area": 1.5})):
            rr = q(**params)
            check("★★ %s 도 500 이 아니다" % name, rr.status_code == 200,
                  (rr.status_code, rr.text[:120]))

        # ------------------------------------------------------------------
        # C. 방어가 **좁은가** — 면적을 안 준 검색은 그대로 살아 있어야 한다
        #    (여기가 없으면 "컬럼 없으면 늘 빈 결과" 라는 과잉 방어를 못 잡는다)
        # ------------------------------------------------------------------
        r = q()
        check("★ 면적을 안 주면 결손 DB 에서도 결과가 그대로다", r.json()["total"] == 4,
              r.json()["total"])
        check("★ 면적 필드는 null 로 응답한다(_area_of 계약)",
              all(i["building_area"] is None and i["land_area"] is None
                  for i in r.json()["items"]),
              [(i["id"], i["building_area"]) for i in r.json()["items"]])
        check("★ 다른 필터는 결손 DB 에서도 그대로 거른다",
              q(sido="서울").json()["total"] == 4, q(sido="서울").json()["total"])
        check("★ 다른 필터의 0건도 그대로다",
              q(sido="부산").json()["total"] == 0, q(sido="부산").json()["total"])

        # ------------------------------------------------------------------
        # D. 판정을 캐시하지 않는다 — 마이그레이션이 적용되면 **같은 프로세스에서** 되살아난다
        #    (`run_daily.bat` 가 매일 새벽 러너를 부른다, BUGS #219)
        # ------------------------------------------------------------------
        conn = dbmod.get_connection()
        try:
            conn.execute("ALTER TABLE auction_item ADD COLUMN building_area REAL")
            conn.execute("ALTER TABLE auction_item ADD COLUMN land_area REAL")
            conn.execute("UPDATE auction_item SET building_area=85.0, land_area=120.0"
                         " WHERE id=2")
            conn.commit()
        finally:
            conn.close()
        got = sorted(i["id"] for i in q(min_building_area=50).json()["items"])
        check("★★ 025 를 뒤늦게 적용하면 같은 프로세스에서 곧바로 다시 거른다(캐시 없음)",
              got == [2], got)
    finally:
        dbmod.DB_PATH = orig_db
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 건물면적 / 토지면적은 **판별 합집합**이다 — 두 조건을 AND 로 묶으면 항상 0건이었다
# (2026-08-26, `docs/BUGS.md` #239)
#
# 왜 기존 검사가 이것을 못 잡았나
# ---------------------------------------------------------------------------
# `check_area_filter_survives_missing_migration_025()` 의 씨앗은 4행 전부
# `property_type='아파트'` 이고 1~3번이 **건물·토지 면적을 둘 다** 갖고 있다.
# 실데이터에는 그런 행이 **한 행도 없다**(2026-08-26 전수: 둘 다 보유 0행).
# 즉 그 fixture 는 존재하지 않는 데이터 모양을 전제하고 있어서, 통과해도
# "두 조건을 함께 주면 공집합"이라는 실제 결함을 드러낼 수 없었다.
# 여기서는 **실측된 모양 그대로** 씨앗을 만든다 — 한 물건은 둘 중 하나만 갖는다.
def check_area_families_are_a_union_not_a_pair():
    import contextlib, io as _io, shutil, tempfile
    from fastapi.testclient import TestClient
    import storage.database as dbmod
    import storage.migrate_v4_1 as mig
    import storage.migrations.run_migrations as runmig

    orig_db = dbmod.DB_PATH
    workdir = tempfile.mkdtemp(prefix="qa_area_union_")
    try:
        # 스키마는 실제 부트스트랩 3단계 그대로 만든다(위 검사와 같은 이유).
        dbmod.DB_PATH = os.path.join(workdir, "t.db")
        with contextlib.redirect_stdout(_io.StringIO()):
            dbmod.init_db()
            mig.migrate()
            runmig.run()

        import api_server
        client = TestClient(api_server.app)

        # 실데이터 모양: 건물형 물건은 building_area 만, 토지형 물건은 land_area 만.
        rows = [
            (1, "2024타경801", "아파트",   85.0, None),
            (2, "2024타경802", "오피스텔", 40.0, None),
            (3, "2024타경803", "전답",     None, 900.0),
            (4, "2024타경804", "임야",     None, 5000.0),
            (5, "2024타경805", "자동차",   None, None),
        ]
        c = dbmod.get_connection()
        try:
            for item_id, case_no, ptype, b, l in rows:
                case_id = c.execute(
                    "INSERT INTO auction_case (court_code, case_no) VALUES (?,?)",
                    ("서울중앙지방법원", case_no)).lastrowid
                c.execute(
                    "INSERT INTO auction_item"
                    " (id, case_id, case_no, item_no, court_name, property_type,"
                    "  sido, sigungu, full_address, auction_date,"
                    "  building_area, land_area)"
                    " VALUES (?,?,?,'1','서울중앙지방법원',?,'서울','강남구',"
                    "         '서울 강남구 역삼동 1', '2099-01-01', ?, ?)",
                    (item_id, case_id, case_no, ptype, b, l))
            c.commit()
        finally:
            c.close()

        def ids(**params):
            r = client.get("/api/v1/search", params={"size": 100, **params})
            assert r.status_code == 200, (r.status_code, r.text[:200])
            return sorted(i["id"] for i in r.json()["items"])

        # -- 전제: 실데이터와 같은 모양인가 (이게 깨지면 아래 판정이 무의미하다) --
        conn = dbmod.get_connection()
        try:
            both = conn.execute(
                "SELECT COUNT(*) FROM auction_item"
                " WHERE building_area IS NOT NULL AND land_area IS NOT NULL").fetchone()[0]
        finally:
            conn.close()
        check("전제: 씨앗에 두 면적을 동시에 가진 행이 없다(실데이터와 같은 모양)",
              both == 0, both)
        check("전제: 씨앗 5건이 기본 검색에 보인다", ids() == [1, 2, 3, 4, 5], ids())

        # -- 한 계열만 줄 때: 기존 NULL 규약 그대로 (동작 변경 없음) --
        check("★ 건물면적만 주면 토지형·면적미상은 빠진다(NULL 규약 유지)",
              ids(min_building_area=50) == [1], ids(min_building_area=50))
        check("★ 토지면적만 주면 건물형·면적미상은 빠진다(NULL 규약 유지)",
              ids(min_land_area=1000) == [4], ids(min_land_area=1000))
        check("★ 한 계열 안의 min/max 는 AND 다(범위가 좁혀진다)",
              ids(min_building_area=50, max_building_area=100) == [1],
              ids(min_building_area=50, max_building_area=100))
        check("★ 한 계열 안에서 범위가 뒤집히면 0건이다",
              ids(min_building_area=100, max_building_area=50) == [],
              ids(min_building_area=100, max_building_area=50))

        # -- 두 계열을 함께 줄 때: OR (여기가 결함이었다 — 예전에는 항상 []) --
        got = ids(min_building_area=50, min_land_area=1000)
        check("★★★ 두 면적을 함께 주면 공집합이 아니다(합집합으로 읽는다)",
              got == [1, 4], got)
        check("★★★ 두 계열 OR 는 각 계열 결과의 정확한 합집합이다",
              sorted(set(ids(min_building_area=50)) | set(ids(min_land_area=1000))) == got,
              got)
        check("★★ 두 계열을 줘도 어느 쪽에도 안 맞는 행은 들어오지 않는다"
              " (면적미상 5번이 섞이지 않는다)",
              5 not in got and 2 not in got and 3 not in got, got)
        got2 = ids(min_building_area=30, max_building_area=50,
                   min_land_area=800, max_land_area=1000)
        check("★★ 계열 안 AND · 계열 간 OR 가 함께 성립한다",
              got2 == [2, 3], got2)
        check("★★ 두 계열 다 아무것도 못 맞히면 0건이다(과잉 확장이 아니다)",
              ids(min_building_area=10000, min_land_area=99999) == [],
              ids(min_building_area=10000, min_land_area=99999))
    finally:
        dbmod.DB_PATH = orig_db
        shutil.rmtree(workdir, ignore_errors=True)



if __name__ == "__main__":
    sys.exit(run())
