"""
현황조사서(STATUS.html)에서 확인 가능한 점유관계 정보만 파싱해
tenant_rights / rights_summary에 적재하는 최소 구현 스크립트.

원칙:
- STATUS.html에 명시된 내용만 근거로 사용한다 (추정/생성 금지)
- 근거 없는 컬럼은 반드시 NULL로 명시적으로 저장한다 (컬럼 기본값에 의존하지 않음)
- "미상"은 "판단보류"로만 변환 허용
"""
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.database import (get_connection, chunked_for_sql, guard_mass_purge,
                              PURGE_BLOCKED)
from api.v1.documents import get_doc_dir


def parse_lease_counts(html: str):
    """'번호,소재지,임대차관계' 그리드 표에서 (소재지, 인원수) 목록 추출"""
    results = []
    address_pattern = re.compile(r'data-col_id="printSt"[^>]*>.*?<nobr[^>]*>([^<]*)</nobr>', re.DOTALL)
    lescnt_pattern = re.compile(r'data-col_id="lesCnt"[^>]*>.*?<nobr[^>]*>(\d+)명</nobr>', re.DOTALL)

    # printSt와 lesCnt는 각 row 안에서 순서대로 나타나므로, row 단위로 잘라 매칭한다
    rows = re.split(r'<tr[^>]*data-tr-id="row2"', html)[1:]
    for row in rows:
        addr_match = address_pattern.search(row)
        cnt_match = lescnt_pattern.search(row)
        if addr_match and cnt_match:
            results.append((addr_match.group(1).strip(), int(cnt_match.group(1))))
    return results


def parse_occupancy_relations(html: str):
    """'부동산의 현황 및 점유관계 조사서' 섹션에서 점유관계 텍스트 목록 추출 (빈 값은 근거 없음으로 제외)"""
    pattern = re.compile(r'_spn_possMngRltn"[^>]*>([^<]*)<')
    values = [m.group(1).strip() for m in pattern.finditer(html)]
    return [v for v in values if v]


def build_rights_summary(lease_counts, occupancy_relations):
    if not lease_counts and not occupancy_relations:
        return None  # 근거 자체가 없으면 row를 만들지 않는다

    total_tenant_count = None
    is_vacant = None
    if lease_counts:
        total_tenant_count = sum(c for _, c in lease_counts)
        is_vacant = 1 if total_tenant_count == 0 else 0

    occupancy_status = None
    occupancy_difficulty = None
    if occupancy_relations:
        unique = list(dict.fromkeys(occupancy_relations))  # 순서 유지 중복 제거
        occupancy_status = "; ".join(unique)
        # 규칙: "미상"이 하나라도 있으면 "판단보류". 그 외 텍스트는 근거 부족으로 등급 매기지 않음(NULL)
        occupancy_difficulty = "판단보류" if any("미상" in r for r in unique) else None

    return {
        "total_tenant_count": total_tenant_count,
        "is_vacant": is_vacant,
        "occupancy_status": occupancy_status,
        "occupancy_difficulty": occupancy_difficulty,
    }


def load_item(conn, item_id: int, court_name: str, case_no: str, item_no: str) -> str:
    doc_dir = get_doc_dir(court_name, case_no, item_no)
    status_path = os.path.join(doc_dir, "status.html")
    if not os.path.exists(status_path):
        return "no_status_file"

    html = open(status_path, encoding="utf-8", errors="ignore").read()
    lease_counts = parse_lease_counts(html)
    occupancy_relations = parse_occupancy_relations(html)
    summary = build_rights_summary(lease_counts, occupancy_relations)

    if summary is None:
        return "no_extractable_data"

    now = datetime.now().isoformat()

    conn.execute("DELETE FROM rights_summary WHERE item_id = ?", (item_id,))
    conn.execute(
        """
        INSERT INTO rights_summary (
            item_id, priority_right, priority_date,
            total_tenant_count, dangerous_tenant_count, total_deposit, estimated_inheritance,
            lien_exists, superficies_exists, foreclosure_note,
            occupancy_status, is_vacant, occupancy_difficulty,
            risk_level, risk_reason, analysis_explanation,
            analysis_version, analysis_date, created_at, updated_at
        ) VALUES (?, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, ?, NULL, NULL, NULL, 1, ?, ?, ?)
        """,
        (
            item_id,
            summary["total_tenant_count"],
            summary["occupancy_status"],
            summary["is_vacant"],
            summary["occupancy_difficulty"],
            now, now, now,
        ),
    )

    conn.execute("DELETE FROM tenant_rights WHERE item_id = ? AND source = 'STATUS'", (item_id,))
    for address, count in lease_counts:
        if count <= 0:
            continue  # 확인된 임차인이 없는 주소는 tenant_rights 행을 만들지 않는다
        for _ in range(count):
            conn.execute(
                """
                INSERT INTO tenant_rights (
                    item_id, tenant_name, occupied_area, deposit, monthly_rent,
                    move_in_date, fixed_date, demand_date, has_demand, source, created_at
                ) VALUES (?, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL, 'STATUS', ?)
                """,
                (item_id, address, now),
            )

    conn.commit()
    return "loaded"


def purge_orphans(conn, missing_file_item_ids, evidence_found: int):
    """근거 문서(status.html)가 사라진 물건의 파생 행을 제거한다.

    이 스크립트의 대원칙은 "STATUS.html에 명시된 내용만 근거로 사용한다"인데,
    `load_item()`은 파일이 없으면 DELETE 이전에 early return 하므로 **한 번 적재된 뒤
    근거 문서가 사라지면 파생 데이터가 영원히 남았다**. 화면은 그 근거를 확인할 수 없는
    "현황조사서 임차인 N명"을 계속 보여준다(2026-08-12 Sprint 62에 1건 실측 발견).

    안전장치 — `evidence_found == 0`이면 아무것도 지우지 않는다.
    documents/ 디렉터리가 통째로 안 보이는 상황(경로 변경/드라이브 미마운트/권한)에서
    "전부 근거 없음"으로 오판해 **전체 권리분석 데이터를 날리는 것**을 막는다.
    실제로 지울 근거는 "다른 물건에서는 문서를 정상적으로 찾았다"는 사실이다.

    파일은 있는데 추출 결과가 비어 있는 경우(`no_extractable_data`)는 **지우지 않는다** —
    파서 회귀로도 같은 증상이 나오므로, 파일 부재라는 명확한 근거가 있을 때만 지운다.
    """
    if evidence_found == 0:
        print("[안전장치] status.html을 하나도 찾지 못해 정리를 건너뛴다 "
              "(documents/ 경로 문제일 수 있으므로 데이터를 지우지 않는다)")
        return 0
    if not missing_file_item_ids:
        return 0

    # ★ 한 문장에 몰아넣지 않는다 (2026-08-27, `docs/BUGS.md` #243).
    #   `missing_file_item_ids` 는 상한이 없다 — documents/ 가 부분적으로 유실되면
    #   물건 수만큼 커진다. SQLite 의 바인딩 변수 상한을 넘으면 정리 자체가
    #   `too many SQL variables` 로 죽는다. 상한은 이 커넥션에 직접 물어본다.
    #
    # ★ 지우기 **전에 먼저 센다** (2026-09-02 — 배선의 전제조건).
    #   `evidence_found == 0` 은 전면 유실만 막는다. 부분 유실(동기화 지연 등)에서는
    #   안전장치가 열린 채 대부분을 지운다. 이 스크립트를 `run_daily.bat` 에 넣는
    #   순간 그 일이 **무인으로** 벌어지므로, 규모를 먼저 재고 차단기에 묻는다.
    existing = (conn.execute("SELECT COUNT(*) FROM rights_summary").fetchone()[0]
                + conn.execute(
                    "SELECT COUNT(*) FROM tenant_rights WHERE source='STATUS'").fetchone()[0])
    to_delete = 0
    for chunk in chunked_for_sql(missing_file_item_ids, conn=conn):
        placeholders = ",".join("?" * len(chunk))
        to_delete += conn.execute(
            "SELECT COUNT(*) FROM rights_summary WHERE item_id IN (%s)" % placeholders,
            chunk).fetchone()[0]
        to_delete += conn.execute(
            "SELECT COUNT(*) FROM tenant_rights WHERE source='STATUS' AND item_id IN (%s)"
            % placeholders, chunk).fetchone()[0]

    blocked = guard_mass_purge(existing, to_delete, "STATUS 파생 행 정리")
    if blocked:
        print("[BLOCKED] " + blocked)
        return PURGE_BLOCKED

    removed = 0
    for chunk in chunked_for_sql(missing_file_item_ids, conn=conn):
        placeholders = ",".join("?" * len(chunk))
        removed += conn.execute(
            "DELETE FROM rights_summary WHERE item_id IN (%s)" % placeholders,
            chunk,
        ).rowcount
        removed += conn.execute(
            "DELETE FROM tenant_rights WHERE source='STATUS' AND item_id IN (%s)" % placeholders,
            chunk,
        ).rowcount
    conn.commit()
    return removed


def main():
    conn = get_connection()
    try:
        items = conn.execute(
            "SELECT id, court_name, case_no, item_no FROM auction_item"
        ).fetchall()

        stats = {"loaded": 0, "no_status_file": 0, "no_extractable_data": 0}
        missing_file_item_ids = []
        for item in items:
            result = load_item(conn, item["id"], item["court_name"], item["case_no"], item["item_no"])
            stats[result] = stats.get(result, 0) + 1
            if result == "no_status_file":
                missing_file_item_ids.append(item["id"])

        removed = purge_orphans(
            conn, missing_file_item_ids,
            evidence_found=stats["loaded"] + stats["no_extractable_data"],
        )

        print("=== 적재 결과 ===")
        print(f"전체 물건: {len(items)}")
        print(f"적재 완료(loaded): {stats['loaded']}")
        print(f"STATUS 파일 없음: {stats['no_status_file']}")
        print(f"STATUS 파일은 있으나 추출 가능한 데이터 없음: {stats['no_extractable_data']}")
        if removed == PURGE_BLOCKED:
            # 부재는 어떤 실패 카운터에도 안 잡힌다(#245 의 교훈). 종료코드로 드러낸다 —
            # `run_daily.bat` 이 [FAILED] 를 남기고 사람이 아침에 본다.
            print("근거 문서가 사라져 정리한 파생 행: 0 (차단됨 - 위 [BLOCKED] 참고)")
            return 1
        print(f"근거 문서가 사라져 정리한 파생 행: {removed}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
