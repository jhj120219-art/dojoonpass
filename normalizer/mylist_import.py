"""경쟁사 마이리스트 **가져오기** 파서 — 2026-08-28 신설.

## 이 파일이 무엇을 하고, 무엇을 하지 않는가

    한다        사용자가 **손으로 복사해 온 텍스트**에서 식별자를 뽑고, 우리 물건과
                맞춰 볼 수 있는 형태로 정규화한다. 순수 함수만 있다(DB 접근 없음).
    하지 않는다  외부 상용 서비스에 접속/로그인/스크래핑. 단 한 줄도 없고,
                이 파일은 네트워크를 쓰지 않는다.

`docs/SPRINT227_MYLIST_EXPORT.md` 가 만든 **내보내기**의 짝이다. 그때 결론은
"상대 서비스의 입력 형식을 모르므로 전용 포맷을 만들지 않는다" 였다. **가져오기는
방향이 반대라 그 제약을 받지 않는다** — 우리가 형식을 정할 필요가 없고, 사람이 이미
클립보드에 담아 온 것을 읽기만 하면 되기 때문이다. 그래서 형식을 **가정하지 않고**
세 갈래를 모두 받는다.

    (1) 우리 CSV/TSV 내보내기를 그대로 되붙임  -> 헤더를 읽어 열로 매핑 (정확)
    (2) 표(스프레드시트/웹 표)에서 복사한 탭 구분 -> 헤더가 있으면 (1), 없으면 (3)
    (3) 아무 형태의 자유 텍스트                 -> 정규식으로 식별자만 추출

## 절대 하지 않는 것 — 값을 지어내지 않는다

이 저장소가 반복해서 경계해 온 "조용한 실패"를 여기서도 그대로 막는다.

  * **병합 사건번호를 쪼개 대표를 고르지 않는다.** `auction_item` 1,876행 중 425행
    (22.7%)이 `2008타경25092 / 2015타경19958` 형태이고, 어느 쪽이 대표인지는
    법원 원천이 정하지 않았다(`docs/SPRINT219B_MYLIST_EXPORT_FEASIBILITY.md` 2-1).
    매칭은 `crawler/resume.py:case_no_matches_list_entry()` 와 **같은 규칙** --
    양쪽을 구성요소로 쪼개 **하나라도 겹치면 같은 물건** -- 을 쓴다.
  * **후보가 여럿이면 하나를 고르지 않는다.** `AMBIGUOUS` 로 돌려 사람이 고르게 한다.
    사건번호만으로 물건을 특정할 수 없다(물건번호가 1이 아닌 행이 33.5%).
  * **못 찾은 줄을 버리지 않는다.** `NOT_FOUND` 로 원문(`raw`)과 함께 돌려준다.
    조용히 사라지면 사용자는 "가져와졌다"고 믿는다.
"""
import re
from typing import List, Optional, Sequence

# 한글 정규화 규칙의 정본은 한 곳이다(`api/constants.py`). 그 모듈은 표준 라이브러리만
# 의존하는 잎 모듈이라 normalizer -> api 순환이 생기지 않는다.
from api.constants import to_nfc

# ---------------------------------------------------------------------------
# 입력 한도. 정상 사용을 막지 않을 만큼 넉넉하되 상한은 둔다
# (`api/v1/search_presets.py` 가 같은 이유로 두는 것과 같은 성격의 방어다).
# 사람이 마이리스트를 복사해 오는 규모는 수십~수백 건이다.
# ---------------------------------------------------------------------------
MAX_TEXT_LENGTH = 200_000
MAX_LINES = 500
MAX_MEMO_LENGTH = 1_000
MAX_TAGS_LENGTH = 200
MAX_TAG_COUNT = 20
MAX_SOURCE_LENGTH = 50

# 행 판정. **오류 코드가 아니라 행의 상태**다 -- 실패한 행도 사용자에게 보여 줘야 하므로
# HTTP 실패로 만들지 않는다.
STATUS_MATCHED = "MATCHED"                    # 우리 물건 1건으로 특정됨
STATUS_ALREADY = "ALREADY_FAVORITED"          # 특정됐고 이미 관심물건이다
STATUS_AMBIGUOUS = "AMBIGUOUS"                # 후보가 둘 이상 -- 사람이 고른다
STATUS_NOT_FOUND = "NOT_FOUND"                # 식별자는 읽었지만 우리 DB 에 없다
STATUS_NO_CASE_NO = "NO_CASE_NO"              # 사건번호를 못 읽었다
STATUS_DUPLICATE_INPUT = "DUPLICATE_IN_INPUT" # 붙여넣은 텍스트 안에서 중복

ALL_STATUSES = (
    STATUS_MATCHED, STATUS_ALREADY, STATUS_AMBIGUOUS,
    STATUS_NOT_FOUND, STATUS_NO_CASE_NO, STATUS_DUPLICATE_INPUT,
)

# 커밋 가능한 상태. `AMBIGUOUS` 는 사용자가 후보를 골라 `item_id` 를 확정한 뒤에만
# 커밋되므로 여기 없다 -- 커밋 API 는 상태가 아니라 **확정된 item_id** 를 받는다.
COMMITTABLE = (STATUS_MATCHED, STATUS_ALREADY)

# ---------------------------------------------------------------------------
# 사건번호
#
# 표기 흔들림을 흡수한다: `2024 타경 1009` / `2024타경1009` / `2024타경 1009`.
# 연도는 4자리, 사건번호 본문은 숫자다. `타경` 말고 다른 사건부호(`타채` 등)는
# 이 제품의 대상이 아니므로 받지 않는다 -- 받아 두면 "읽었는데 못 찾음"으로 보인다.
# ---------------------------------------------------------------------------
CASE_NO_RE = re.compile(r"(\d{4})\s*타경\s*(\d{1,7})")

# `2024타경1009-3` 처럼 **붙여 쓴** 물건번호. 공백이 끼면 받지 않는다 --
# `2024타경1009 - 3` 은 지번(`123-4`)이나 범위 표기와 구별할 수 없다.
CASE_WITH_ITEM_RE = re.compile(r"(\d{4})\s*타경\s*(\d{1,7})-(\d{1,3})(?!\d)")

# 명시적 물건번호. 열 이름이 없는 자유 텍스트에서만 쓴다.
ITEM_NO_RE = re.compile(r"물건\s*(?:번호)?\s*[:：]?\s*(\d{1,3})(?!\d)")

# 법원명. `서울중앙지방법원` / `안산지원` 두 계열이 전부다(실측 60종: 지방법원 18 + 지원 42).
COURT_RE = re.compile(r"([가-힣]{2,10}(?:지방법원|지원))")

# 태그. `#단독주택` 처럼 사람이 흔히 쓰는 표기만 받는다.
TAG_RE = re.compile(r"#([0-9A-Za-z가-힣_]{1,20})")

# 우리 CSV/TSV 내보내기의 헤더(`src/lib/exportList.ts:COLUMNS`)와 **같은 이름**을 읽는다.
# * 이 표는 그 파일과 짝이다. 한쪽만 바뀌면 되붙이기가 조용히 자유형으로 떨어진다 --
#   `test_favorite_import.py` 의 13번(`test_export_header_contract`)이 두 목록의
#   일치를 고정한다 — 열 이름 대조에 그치지 않고 **실제로 되붙여** 헤더로 읽히는지,
#   각 열이 의도한 필드로 매핑되는지까지 확인한다.
#   (2026-08-31 정정: 예전 주석은 tests/ 아래의 어떤 .mjs 계약 파일을 가리켰는데
#    **그 파일은 존재한 적이 없다**(저장소 전체 검색 결과 그 이름을 언급하는 곳은
#    이 주석 한 줄뿐이었다). 짝을 지킨다고 적어 두고 지키는 것이 없는 것처럼 보였다 —
#    실제 보증은 처음부터 위 파이썬 검사가 하고 있었다. 죽은 인용을 남기지 않으려고
#    그 이름은 여기 다시 적지 않는다: 아래 검사가 인용 경로의 실재를 확인한다.)
HEADER_ALIASES = {
    "법원": "court_name",
    "법원명": "court_name",
    "사건번호": "case_no",
    "사건": "case_no",
    "물건번호": "item_no",
    "물건": "item_no",
    "소재지": "address",
    "주소": "address",
    "메모": "memo",
    "비고": "memo",
    "태그": "tags",
}


def normalize_case_no(text: Optional[str]) -> str:
    """텍스트에서 사건번호를 뽑아 표준 표기로 되돌린다.

    여러 개가 나오면 **원문 순서대로 `" / "` 로 잇는다** -- 병합 사건의 저장 표기와
    같은 모양이다(`crawler/base_crawler.py` 의 `" / ".join(case_nos)`).
    같은 값이 두 번 나오면 한 번만 남긴다(순서는 첫 등장 기준).

        "2024 타경 1009"                     -> "2024타경1009"
        "2008타경25092 / 2015타경19958"       -> "2008타경25092 / 2015타경19958"
        "사건번호 없음"                        -> ""            (빈 문자열 = 모른다)
    """
    parts: List[str] = []
    for year, serial in CASE_NO_RE.findall(text or ""):
        value = "%s타경%s" % (year, serial)
        if value not in parts:
            parts.append(value)
    return " / ".join(parts)


def case_no_parts(case_no: Optional[str]) -> set:
    """`"A / B"` -> `{"A", "B"}`. 비어 있으면 빈 집합.

    `crawler/resume.py:_case_no_parts()` 와 **같은 규칙**이다. 두 벌을 만든 것이 아니라,
    저쪽은 크롤 재개(목록 항목)용이고 이쪽은 사용자 입력용이라 의존 방향이 반대다
    (api/ 가 crawler/ 를 import 하면 API 서버가 Selenium 계열을 끌고 들어온다).
    **규칙이 갈리지 않는지는 검사가 두 함수를 나란히 태워 고정한다.**
    """
    return {part.strip() for part in (case_no or "").split(" / ") if part.strip()}


def case_no_matches(a: Optional[str], b: Optional[str]) -> bool:
    """구성요소를 하나라도 공유하면 같은 물건이다. 빈 값은 아무것도 일치시키지 않는다."""
    return bool(case_no_parts(a) & case_no_parts(b))


def _clip(value: Optional[str], limit: int) -> str:
    text = (value or "").strip()
    return text[:limit]


def _split_fields(line: str) -> List[str]:
    """한 줄을 열로 쪼갠다. 탭이 있으면 탭 우선(스프레드시트 복사), 없으면 쉼표.

    * 쉼표는 **따옴표를 존중해야 한다.** 우리 내보내기가 RFC 4180 으로 감싸 주는데
      (`물건종류` 에 `상가,오피스텔,근린시설` 처럼 쉼표가 실제로 들어 있다) 여기서
      단순 `split(",")` 을 쓰면 열이 밀려 사건번호 칸에 엉뚱한 값이 들어간다.
    """
    if "\t" in line:
        return [f.strip() for f in line.split("\t")]
    return _split_csv_line(line)


def _split_csv_line(line: str) -> List[str]:
    """RFC 4180 한 줄 파서. 따옴표 안의 쉼표는 경계가 아니고, `""` 는 리터럴 `"` 다."""
    fields: List[str] = []
    buf: List[str] = []
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < len(line) and line[i + 1] == '"':
                    buf.append('"')
                    i += 2
                    continue
                in_quotes = False
            else:
                buf.append(ch)
        elif ch == '"':
            in_quotes = True
        elif ch == ",":
            fields.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    fields.append("".join(buf).strip())
    return fields


def _looks_like_header(fields: Sequence[str]) -> bool:
    """헤더 줄인가 -- 사건번호 열이 있고 **그 줄 자체에는 사건번호 값이 없어야** 한다.

    두 조건을 모두 보는 이유: `사건번호` 라는 낱말이 데이터 줄에 섞여 있을 수 있다
    (`사건번호 2024타경1009` 같은 자유형 한 줄). 값이 들어 있으면 데이터다.
    """
    if not any(HEADER_ALIASES.get(f.strip()) == "case_no" for f in fields):
        return False
    return not CASE_NO_RE.search(" ".join(fields))


def _extract_tags(text: str) -> List[str]:
    tags: List[str] = []
    for tag in TAG_RE.findall(text or ""):
        if tag not in tags and len(tags) < MAX_TAG_COUNT:
            tags.append(tag)
    return tags


def _parse_tag_field(text: str) -> List[str]:
    """태그 **열**은 `#` 없이 쉼표/공백으로 나열될 수 있다. 둘 다 받는다."""
    hashed = _extract_tags(text)
    if hashed:
        return hashed
    tags: List[str] = []
    for raw in re.split(r"[,\s]+", (text or "").strip()):
        tag = raw.strip().lstrip("#")
        if tag and tag not in tags and len(tags) < MAX_TAG_COUNT:
            tags.append(tag[:20])
    return tags


def _parse_freeform(line: str) -> dict:
    """열 이름이 없는 줄에서 식별자만 뽑는다."""
    case_no = normalize_case_no(line)
    item_no = None

    # 붙여 쓴 `-N` 을 먼저 본다. 여러 개면 **쓰지 않는다** -- 병합 사건에 각각 다른
    # 물건번호가 붙은 표기는 우리가 해석할 수 없다(사람이 고르게 남긴다).
    attached = CASE_WITH_ITEM_RE.findall(line)
    if len(attached) == 1:
        item_no = attached[0][2]
    else:
        explicit = ITEM_NO_RE.search(line)
        if explicit:
            item_no = explicit.group(1)

    court = COURT_RE.search(line)
    tags = _extract_tags(line)

    # 주소 힌트: 식별자/태그를 걷어낸 나머지. **매칭을 좁히는 데만** 쓰고
    # 이것만으로 물건을 특정하지 않는다.
    leftover = CASE_NO_RE.sub(" ", line)
    leftover = COURT_RE.sub(" ", leftover)
    leftover = TAG_RE.sub(" ", leftover)
    leftover = re.sub(r"[\t,]+", " ", leftover)
    leftover = re.sub(r"\s+", " ", leftover).strip()

    return {
        "case_no": case_no,
        "item_no": item_no,
        "court_name": court.group(1) if court else None,
        "address": leftover or None,
        "memo": "",
        "tags": tags,
    }


def _parse_mapped(fields: Sequence[str], mapping: dict) -> dict:
    """헤더가 있는 줄. 열 이름이 말해 주는 것을 **추측하지 않고** 그대로 쓴다."""
    def col(key: str) -> str:
        idx = mapping.get(key)
        if idx is None or idx >= len(fields):
            return ""
        return fields[idx].strip()

    raw_case = col("case_no")
    case_no = normalize_case_no(raw_case)

    item_raw = col("item_no")
    item_match = re.search(r"\d{1,3}", item_raw)
    item_no = item_match.group(0) if item_match else None
    # 물건번호 열이 비어 있으면 사건번호 칸의 `-N` 을 본다(둘 다 없으면 모른다).
    if item_no is None:
        attached = CASE_WITH_ITEM_RE.findall(raw_case)
        if len(attached) == 1:
            item_no = attached[0][2]

    court_raw = col("court_name")
    court_match = COURT_RE.search(court_raw)

    memo = col("memo")
    tags = _parse_tag_field(col("tags"))
    if not tags:
        tags = _extract_tags(memo)

    return {
        "case_no": case_no,
        # 열 이름이 `법원` 이면 그 칸이 법원명이다. 정규식에 걸리지 않아도(표기가
        # 우리와 달라도) 값을 버리지 않는다 -- 버리면 화면에서 사유를 알 수 없다.
        "court_name": (court_match.group(1) if court_match else court_raw) or None,
        "item_no": item_no,
        "address": col("address") or None,
        "memo": memo,
        "tags": tags,
    }


def parse_mylist_text(text: Optional[str]) -> dict:
    """붙여넣은 텍스트를 행 목록으로 바꾼다. **DB 를 보지 않는다.**

    돌려주는 것:
        {"rows": [...], "truncated": bool, "header_detected": bool}

    각 행:
        line_no / raw / case_no / item_no / court_name / address / memo / tags

    빈 줄은 건너뛰되 `line_no` 는 **원문 줄 번호**를 유지한다 -- 화면이 "3번째 줄이
    이상하다"고 말할 때 사용자가 세는 줄과 같아야 한다.
    """
    # 줄바꿈과 **한글 표현**을 같은 자리에서 한 번에 맞춘다 (2026-09-02).
    #
    # macOS 는 파일 이름을 NFD(자모 분해)로 보관한다. 거기서 복사한 목록을 붙여 넣으면
    # '타경' 이 NFD 로 들어오고, `CASE_NO_RE` 의 `타경` 은 NFC 라 **정규식이 아예 맞지
    # 않는다.** 실측(2026-09-02, 수정 전):
    #
    #     CASE_NO_RE.search(NFC("2024타경1009"))  -> 맞음
    #     CASE_NO_RE.search(NFD("2024타경1009"))  -> **안 맞음**
    #
    # 결과는 조용하다 — 오류도 없이 "가져올 항목 0건"이 되고, 사용자는 자기가 붙여 넣은
    # 목록이 왜 비었는지 알 수 없다. 여기서 한 번 맞추면 사건번호·법원명·주소·메모·태그가
    # 전부 같은 표현을 쓴다(필드마다 흩어 두면 한 곳이 빠지는 날이 온다).
    # 정본은 `api/constants.py:to_nfc` 한 곳이다.
    source = to_nfc((text or "")[:MAX_TEXT_LENGTH])
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    mapping: dict = {}
    header_detected = False
    rows: List[dict] = []
    truncated = False

    for idx, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        if len(rows) >= MAX_LINES:
            truncated = True
            break

        fields = _split_fields(line)
        if not header_detected and _looks_like_header(fields):
            for pos, name in enumerate(fields):
                key = HEADER_ALIASES.get(name.strip())
                # 같은 뜻의 열이 두 번 나오면 **첫 번째**를 쓴다(뒤엣것으로 덮으면
                # 우리 내보내기의 `소재지` 뒤에 사용자가 붙인 빈 `주소` 열이 이긴다).
                if key and key not in mapping:
                    mapping[key] = pos
            header_detected = True
            continue

        parsed = _parse_mapped(fields, mapping) if mapping else _parse_freeform(line)
        parsed["line_no"] = idx
        parsed["raw"] = line.strip()[:500]
        parsed["memo"] = _clip(parsed.get("memo"), MAX_MEMO_LENGTH)
        parsed["tags"] = parsed.get("tags") or []
        rows.append(parsed)

    return {"rows": rows, "truncated": truncated, "header_detected": header_detected}


def resolve_row(parsed: dict, candidates: Sequence[dict]) -> dict:
    """한 행을 후보 물건들과 맞춘다. **순수 함수** -- 후보는 호출부가 DB 에서 가져온다.

    후보 dict 가 가져야 하는 것: `id` / `case_no` / `item_no` / `court_name` / `full_address`.

    좁히는 순서와 **왜 그 순서인가**:

        1. 사건번호 구성요소 겹침   필수. 겹치지 않으면 다른 물건이다.
        2. 물건번호                사용자가 줬을 때만. 사건번호만으로는 특정이 안 된다
                                  (물건번호가 1이 아닌 행 33.5%).
        3. 법원명                  후보가 아직 여럿일 때만 쓴다. 표기가 우리와 다를 수
                                  있어서(상대가 법원 코드를 쓸 수도 있다) **줄이는 데만**
                                  쓰고, 이걸로 0건이 되면 **되돌린다** -- 표기 차이 때문에
                                  "없음"이라고 말하면 그것이 조용한 오답이다.
        4. 주소 힌트               같은 이유로 마지막. 0건이 되면 되돌린다.

    결과: {"status", "item_id", "candidate_ids", "narrowed_by"}
    """
    if not parsed.get("case_no"):
        return {"status": STATUS_NO_CASE_NO, "item_id": None,
                "candidate_ids": [], "narrowed_by": []}

    matches = [c for c in candidates if case_no_matches(parsed["case_no"], c.get("case_no"))]
    if not matches:
        return {"status": STATUS_NOT_FOUND, "item_id": None,
                "candidate_ids": [], "narrowed_by": []}

    narrowed: List[str] = []

    item_no = parsed.get("item_no")
    if item_no:
        by_item = [c for c in matches if str(c.get("item_no") or "").strip() == str(item_no)]
        if by_item:
            matches = by_item
            narrowed.append("item_no")
        # 안 맞으면 되돌린다. 물건번호가 어긋난 것은 "틀렸다"일 수도 있지만
        # 표기 차이(공백/0 채움)일 수도 있어, 여기서 0건으로 만들지 않는다.

    if len(matches) > 1 and parsed.get("court_name"):
        want = re.sub(r"\s+", "", parsed["court_name"])
        by_court = [c for c in matches
                    if want and want in re.sub(r"\s+", "", c.get("court_name") or "")]
        if by_court:
            matches = by_court
            narrowed.append("court_name")

    if len(matches) > 1 and parsed.get("address"):
        want = re.sub(r"\s+", "", parsed["address"])
        if len(want) >= 4:
            by_addr = [c for c in matches
                       if want in re.sub(r"\s+", "", c.get("full_address") or "")]
            if by_addr:
                matches = by_addr
                narrowed.append("address")

    if len(matches) == 1:
        return {"status": STATUS_MATCHED, "item_id": matches[0]["id"],
                "candidate_ids": [matches[0]["id"]], "narrowed_by": narrowed}

    return {"status": STATUS_AMBIGUOUS, "item_id": None,
            "candidate_ids": [c["id"] for c in matches], "narrowed_by": narrowed}


def dedupe_key(parsed: dict) -> Optional[tuple]:
    """붙여넣기 안의 중복 판정 키. 사건번호 구성요소 집합 + 물건번호.

    구성요소 **집합**을 쓰는 이유: `"A / B"` 와 `"B / A"` 는 같은 물건이다.
    사건번호를 못 읽은 줄은 중복 판정에서 뺀다(빈 값끼리 묶으면 서로 다른 오류 줄이
    "중복"으로 감춰진다 -- 사용자가 고쳐야 할 줄이 사라진다).
    """
    parts = case_no_parts(parsed.get("case_no"))
    if not parts:
        return None
    return (frozenset(parts), str(parsed.get("item_no") or ""))


def normalize_tags(tags) -> str:
    """태그 목록을 저장 표기(쉼표 구분)로. 빈 값/중복/길이 상한을 여기 한 곳에서 정한다."""
    if isinstance(tags, str):
        tags = re.split(r"[,\s]+", tags)
    out: List[str] = []
    for raw in tags or []:
        tag = str(raw).strip().lstrip("#")[:20]
        if tag and tag not in out and len(out) < MAX_TAG_COUNT:
            out.append(tag)
    joined = ",".join(out)
    return joined[:MAX_TAGS_LENGTH]
