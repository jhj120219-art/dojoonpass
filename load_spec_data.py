"""
매각물건명세서(SPEC.pdf)의 "임차인현황" 표에서 확인 가능한 정보만 파싱해
tenant_rights에 적재하는 스크립트 (source='SPEC').

원칙:
- 좌표 기반 표 재구성은 pdfplumber에 위임한다 (직접 좌표 계산 금지 - 오매칭 위험).
- 헤더 텍스트로 열을 식별한다 (헤더를 못 찾으면 그 문서는 스킵 - 인덱스 추정 금지).
- 추출 실패/공란은 NULL로 저장한다 (컬럼 기본값에 의존하지 않음).
- STATUS 기반 tenant_rights(source='STATUS') 행과는 병합하지 않고,
  source='SPEC'으로 별도 행을 추가한다 (occupied_area 표기 형식이 서로 달라
  안전하게 매칭할 근거가 없기 때문).
"""
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pdfplumber
from storage.database import (get_connection, chunked_for_sql, guard_mass_purge,
                              PURGE_BLOCKED)
from api.v1.documents import get_doc_dir
from api.constants import DocumentType

# `load_rights_data.py:_SOURCE` 와 같은 이유다 - 이 파일도 같은 값을
# 다섯 자리에서 반복했고 그중 셋이 대량 삭제 차단기다(2026-09-04).
_SOURCE = DocumentType.SPEC.value

# 헤더 셀 텍스트 -> 필드명 매칭 규칙.
# 원본 서식이 "보 증 금"처럼 글자 사이에 공백을 넣는 경우가 있어, 매칭은 공백을 모두 제거한
# 텍스트(_compact)를 기준으로 한다 (저장/표시용 clean_cell과는 별도).
HEADER_RULES = [
    ("tenant_name", lambda t: "성" in t and "명" in t),
    ("occupied_area", lambda t: "점유" in t and "부분" in t),
    ("deposit", lambda t: "보증금" in t),
    ("monthly_rent", lambda t: "차임" in t),
    ("move_in_date", lambda t: "전입" in t),
    ("fixed_date", lambda t: "확정일자" in t),
    ("demand_date", lambda t: "배당" in t and "요구" in t),
]


def clean_cell(cell):
    if cell is None:
        return None
    text = re.sub(r'\s+', ' ', str(cell)).strip()
    return text if text else None


def _compact(text):
    return re.sub(r'\s+', '', text)


def find_tenant_table(pdf):
    """모든 페이지의 표를 훑어 임차인현황 표(헤더 키워드로 식별)를 찾는다."""
    for page in pdf.pages:
        for table in page.extract_tables():
            if not table:
                continue
            for row in table:
                cells = [clean_cell(c) for c in row]
                matched = {name for name, rule in HEADER_RULES
                           for c in cells if c and rule(_compact(c))}
                # 설명 문장 한 셀에 키워드가 우연히 몰려 있는 경우(예: 표 상단 안내문)를
                # 배제하기 위해, 성명/점유부분까지 포함해 여러 셀에 걸쳐 매칭되는 행만
                # 진짜 헤더 행으로 인정한다.
                if {"tenant_name", "occupied_area"} <= matched and len(matched) >= 3:
                    return table, row
    return None, None


def build_column_map(header_row):
    col_map = {}
    for idx, cell in enumerate(header_row):
        text = clean_cell(cell)
        if not text:
            continue
        for name, rule in HEADER_RULES:
            if name not in col_map and rule(_compact(text)):
                col_map[name] = idx
    return col_map


def parse_date(text):
    """셀에 날짜가 정확히 1개일 때만 변환한다. 계약 갱신 등으로 날짜가
    여러 개 병기된 셀은 어느 것이 대표값인지 판단할 근거가 없으므로 NULL 처리한다."""
    if not text:
        return None
    matches = re.findall(r'(\d{4})\.(\d{1,2})\.(\d{1,2})\.?', text)
    if len(matches) != 1:
        return None
    y, mo, d = matches[0]
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def parse_amount(text):
    """셀에 금액이 정확히 1개일 때만 변환한다. 계약 갱신 등으로 금액이
    여러 개 병기된 셀은 합산/대표값 선택 근거가 없으므로 NULL 처리한다
    (실제로 여러 금액이 붙어 거대한 숫자로 잘못 합쳐지는 사례를 확인함)."""
    if not text:
        return None
    matches = re.findall(r'\d{1,3}(?:,\d{3})+|\d+', text)
    if len(matches) != 1:
        return None
    digits = matches[0].replace(',', '')
    return int(digits) if digits else None


def extract_tenants(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        table, header_row = find_tenant_table(pdf)
        if table is None:
            return None  # 임차인현황 표 자체를 찾지 못함

        col_map = build_column_map(header_row)
        required = {"tenant_name", "deposit", "fixed_date"}
        if not required.issubset(col_map.keys()):
            return None  # 필수 열을 식별하지 못하면 이 표는 신뢰하지 않음

        header_idx = table.index(header_row)
        tenants = []
        for row in table[header_idx + 1:]:
            cells = [clean_cell(c) for c in row]
            if any(c and ("비고" in c) for c in cells):
                break  # 표 끝(비고란) 도달

            def get(field):
                idx = col_map.get(field)
                return cells[idx] if idx is not None and idx < len(cells) else None

            name = get("tenant_name")
            if not name:
                continue  # 성명 없는 행(줄바꿈/병합 잔여 행)은 임차인으로 취급하지 않음
            if "없음" in name:
                continue  # "조사된 임차내역없음" 등 부정 문구가 성명 칸에 들어온 경우 - 임차인 아님

            demand_date_raw = get("demand_date")
            demand_date = parse_date(demand_date_raw)
            has_demand = 1 if demand_date_raw else (0 if demand_date_raw == "" else None)

            tenants.append({
                "tenant_name": name,
                "occupied_area": get("occupied_area"),
                "deposit": parse_amount(get("deposit")),
                "monthly_rent": parse_amount(get("monthly_rent")),
                "move_in_date": parse_date(get("move_in_date")),
                "fixed_date": parse_date(get("fixed_date")),
                "demand_date": demand_date,
                "has_demand": has_demand,
            })
        return tenants


# ---------------------------------------------------------------------------
# 사건 정보(배당요구종기 / 사건종류) — 매각물건명세서 1쪽에 있다
#
# `auction_case` 에 `case_type` / `filed_date` / `demand_deadline` 컬럼이 있고
# `api/v1/item.py:_CASE_FIELDS` 가 그대로 내보내며 상세 화면이 표시까지 한다.
# 그런데 **채우는 코드가 없었다** — 실측 2026-08-30 기준 1,960 사건 전부 NULL 이라
# 화면에는 늘 `-` 만 나왔다(수집만 빠진 상태).
#
# 이미 받아 둔 `spec.pdf` 1쪽에 그 값이 있다. 새로 크롤하지 않는다.
#
#   "... 사건 2021타경30541 부동산강제경매 ... 배당요구종기 2021. 5. 26. ..."
#
# 실측 추출률(보유 spec.pdf 371개):
#
#     배당요구종기  352건 (94.9%)
#     사건종류      363건 (97.8%)
#     열기 실패       0건
#     사건종류 분포  부동산임의경매 215 / 부동산강제경매 148
#
# ★ 1쪽만 읽는다. 전 쪽을 훑어도 결과가 **똑같았고**(352 대 352) spec.pdf 는 최대
#   30쪽짜리도 있어 비용만 커진다.
#
# ★ `filed_date`(접수일)는 이 문서에 없다. 사건 요약 화면에만 있어 크롤이 필요하다
#   -> 여기서는 건드리지 않는다(그 컬럼은 계속 NULL).
# ---------------------------------------------------------------------------
CASE_DEADLINE_RE = re.compile(
    r"배당요구종기(?:일)?\s*[:：]?\s*"
    r"(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})")
CASE_TYPE_RE = re.compile(r"\d{4}타경\d+\s*(부동산[가-힣]{2,10}경매)")


def parse_case_info(text):
    """명세서 본문 -> {"demand_deadline", "case_type"}. 못 읽으면 None 을 담는다.

    **순수 함수**다 — 파일도 DB 도 건드리지 않아 검사가 직접 태울 수 있다
    (`crawler/doc_paths.py` 나 `crawler/resume.py` 와 같은 방식).
    """
    out = {"demand_deadline": None, "case_type": None}
    m = CASE_DEADLINE_RE.search(text or "")
    if m:
        out["demand_deadline"] = "%04d-%02d-%02d" % (
            int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m2 = CASE_TYPE_RE.search(text or "")
    if m2:
        out["case_type"] = m2.group(1)
    return out


def extract_case_info(pdf_path):
    """spec.pdf **1쪽**에서 사건 정보를 읽는다."""
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return {"demand_deadline": None, "case_type": None}
        return parse_case_info(pdf.pages[0].extract_text() or "")


def update_case_info(conn, court_name: str, case_no: str, info) -> bool:
    """`auction_case` 의 사건 정보를 채운다. **값이 같으면 쓰지 않는다.**

    돌려주는 값: 실제로 행을 바꿨으면 True.

    읽은 값이 없는 필드(None)는 기존 값을 지우지 않는다 — 이 문서에서 못 읽었다는
    뜻이지 "값이 없다"는 뜻이 아니다(`COALESCE` 로 보존한다).
    """
    if not info or not any(info.values()):
        return False
    cur = conn.execute(
        "UPDATE auction_case"
        "   SET case_type       = COALESCE(?, case_type),"
        "       demand_deadline = COALESCE(?, demand_deadline),"
        "       updated_at      = ?"
        " WHERE court_code = ? AND case_no = ?"
        "   AND (IFNULL(case_type,'')       <> IFNULL(COALESCE(?, case_type),'')"
        "     OR IFNULL(demand_deadline,'') <> IFNULL(COALESCE(?, demand_deadline),''))",
        (info.get("case_type"), info.get("demand_deadline"),
         datetime.now().isoformat(), court_name, case_no,
         info.get("case_type"), info.get("demand_deadline")))
    return bool(cur.rowcount)


def load_item(conn, item_id: int, court_name: str, case_no: str, item_no: str) -> str:
    doc_dir = get_doc_dir(court_name, case_no, item_no)
    spec_path = os.path.join(doc_dir, "spec.pdf")
    if not os.path.exists(spec_path):
        return "no_spec_file"

    # ★ 사건 정보는 임차인 표와 **독립**이다. 아래 임차인 경로는 표를 못 찾으면
    #   조기 반환하는데(`no_tenant_table` / `table_found_no_rows`, 실측 139건),
    #   그 물건들도 사건 정보는 정상적으로 들어 있다. 그래서 **먼저** 채운다.
    #   사건 정보 실패가 임차인 적재를 막지 않는다(반대도 마찬가지다).
    try:
        update_case_info(conn, court_name, case_no, extract_case_info(spec_path))
        conn.commit()
    except Exception:                       # noqa: BLE001 - 부가 정보가 본 경로를 죽이지 않는다
        print("  [warn] 사건 정보 읽기 실패: %s %s" % (court_name, case_no))

    try:
        tenants = extract_tenants(spec_path)
    except Exception:
        return "parse_error"

    if tenants is None:
        return "no_tenant_table"
    if len(tenants) == 0:
        return "table_found_no_rows"

    now = datetime.now().isoformat()
    conn.execute("DELETE FROM tenant_rights WHERE item_id = ? AND source = ?",
                 (item_id, _SOURCE))
    for t in tenants:
        conn.execute(
            """
            INSERT INTO tenant_rights (
                item_id, tenant_name, occupied_area, deposit, monthly_rent,
                move_in_date, fixed_date, demand_date, has_demand, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id, t["tenant_name"], t["occupied_area"], t["deposit"], t["monthly_rent"],
                t["move_in_date"], t["fixed_date"], t["demand_date"], t["has_demand"],
                _SOURCE, now,
            ),
        )
    conn.commit()
    return "loaded"


def purge_orphans(conn, missing_file_item_ids, evidence_found: int):
    """근거 문서(spec.pdf)가 사라진 물건의 SPEC 파생 행을 제거한다.

    `load_rights_data.py:purge_orphans()`와 같은 이유·같은 안전장치다(그쪽 docstring 참고).
    `load_item()`이 파일 부재 시 DELETE 이전에 early return 하므로, 한 번 적재된 뒤
    근거 문서가 사라지면 파생 행이 영원히 남는다(2026-08-12 Sprint 62에 1건 실측 발견 —
    STATUS/SPEC 양쪽 모두 같은 물건에서 발생했다).

    `evidence_found == 0`이면 아무것도 지우지 않는다 — documents/ 를 통째로 못 읽는
    상황에서 전체 임차인 데이터를 날리지 않기 위해서다.

    파싱 실패(`parse_error`)나 표가 없는 경우(`no_tenant_table`)는 **지우지 않는다** —
    파서/라이브러리 회귀로도 같은 증상이 나오므로 파일 부재라는 명확한 근거일 때만 지운다.
    """
    if evidence_found == 0:
        print("[안전장치] spec.pdf를 하나도 찾지 못해 정리를 건너뛴다 "
              "(documents/ 경로 문제일 수 있으므로 데이터를 지우지 않는다)")
        return 0
    if not missing_file_item_ids:
        return 0

    # ★ 한 문장에 몰아넣지 않는다 (2026-08-27, `docs/BUGS.md` #243).
    #   위 `load_rights_data.py` 와 같은 이유·같은 규칙이다.
    #
    # ★ 대량 삭제 차단기 (2026-09-02). 판정 규칙은 `storage/database.py:guard_mass_purge()`
    #   한 곳에만 둔다 — 같은 규칙을 두 스크립트에 베끼면 갈라진다(BUGS #204).
    existing = conn.execute(
        "SELECT COUNT(*) FROM tenant_rights WHERE source=?", (_SOURCE,)).fetchone()[0]
    to_delete = 0
    for chunk in chunked_for_sql(missing_file_item_ids, conn=conn):
        placeholders = ",".join("?" * len(chunk))
        to_delete += conn.execute(
            "SELECT COUNT(*) FROM tenant_rights WHERE source=? AND item_id IN (%s)"
            % placeholders, [_SOURCE] + list(chunk)).fetchone()[0]

    blocked = guard_mass_purge(existing, to_delete, "SPEC 파생 행 정리")
    if blocked:
        print("[BLOCKED] " + blocked)
        return PURGE_BLOCKED

    removed = 0
    for chunk in chunked_for_sql(missing_file_item_ids, conn=conn):
        placeholders = ",".join("?" * len(chunk))
        removed += conn.execute(
            "DELETE FROM tenant_rights WHERE source=? AND item_id IN (%s)" % placeholders,
            [_SOURCE] + list(chunk),
        ).rowcount
    conn.commit()
    return removed


def main():
    conn = get_connection()
    try:
        items = conn.execute(
            "SELECT id, court_name, case_no, item_no FROM auction_item"
        ).fetchall()

        stats = {}
        missing_file_item_ids = []
        for item in items:
            result = load_item(conn, item["id"], item["court_name"], item["case_no"], item["item_no"])
            stats[result] = stats.get(result, 0) + 1
            if result == "no_spec_file":
                missing_file_item_ids.append(item["id"])

        # spec.pdf를 실제로 연 물건 수 — 파일 부재를 뺀 나머지 전부가 근거가 된다.
        evidence_found = sum(v for k, v in stats.items() if k != "no_spec_file")
        removed = purge_orphans(conn, missing_file_item_ids, evidence_found)

        print("=== SPEC 적재 결과 ===")
        print(f"전체 물건: {len(items)}")
        for k, v in sorted(stats.items()):
            print(f"{k}: {v}")
        if removed == PURGE_BLOCKED:
            print("근거 문서가 사라져 정리한 파생 행: 0 (차단됨 - 위 [BLOCKED] 참고)")
            return 1
        print(f"근거 문서가 사라져 정리한 파생 행: {removed}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
