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
from storage.database import get_connection
from api.v1.documents import get_doc_dir

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


def load_item(conn, item_id: int, court_name: str, case_no: str, item_no: str) -> str:
    doc_dir = get_doc_dir(court_name, case_no, item_no)
    spec_path = os.path.join(doc_dir, "spec.pdf")
    if not os.path.exists(spec_path):
        return "no_spec_file"

    try:
        tenants = extract_tenants(spec_path)
    except Exception:
        return "parse_error"

    if tenants is None:
        return "no_tenant_table"
    if len(tenants) == 0:
        return "table_found_no_rows"

    now = datetime.now().isoformat()
    conn.execute("DELETE FROM tenant_rights WHERE item_id = ? AND source = 'SPEC'", (item_id,))
    for t in tenants:
        conn.execute(
            """
            INSERT INTO tenant_rights (
                item_id, tenant_name, occupied_area, deposit, monthly_rent,
                move_in_date, fixed_date, demand_date, has_demand, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'SPEC', ?)
            """,
            (
                item_id, t["tenant_name"], t["occupied_area"], t["deposit"], t["monthly_rent"],
                t["move_in_date"], t["fixed_date"], t["demand_date"], t["has_demand"], now,
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

    placeholders = ",".join("?" * len(missing_file_item_ids))
    removed = conn.execute(
        "DELETE FROM tenant_rights WHERE source='SPEC' AND item_id IN (%s)" % placeholders,
        missing_file_item_ids,
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
        print(f"근거 문서가 사라져 정리한 파생 행: {removed}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
