"""이미 수집된 문서의 실체 정보를 `doc_raw`에 채운다 (2026-08-17 Sprint 144 신설).

같은 계열의 다른 백필 스크립트(`backfill_region_normalize.py`,
`backfill_dong_normalize.py`)와 **같은 관례**를 따른다 — 기본은 dry-run,
`--apply`를 줘야 실제로 쓴다.

왜 필요한가 (2026-08-17 실측, auction.db)
-----------------------------------------------------------------------------
디스크에는 실제 법원 문서가 **559개** 있고 `document_status`의 READY도 **556행**인데
`doc_raw`는 **0행**이었다. 즉 "파일과 상태는 맞는데 실체 메타데이터만 통째로 비어 있는"
상태다.

    documents/ 실측   appraisal.pdf 198 / spec.pdf 198 / status.json 163 / status.html 163
    document_status   READY 556 (SPEC 197 / APPRAISAL 197 / STATUS 162)
    doc_raw           0행
    parsed_document   0행

원인은 **쓰는 코드가 실행되지 않는 경로에만 있었던 것**이다:

    doc_raw에 INSERT하는 코드  ->  collect_documents.py:save_doc_raw()  (단 한 곳)
    그 스크립트를 실행하는 것  ->  없음 (스케줄러 3개 어디에도 없다)
    실제로 도는 수집 경로      ->  doc_worker.py -> collect_document() -> mark_queue_done()
                                  (여기에는 doc_raw 기록이 아예 없었다)

Sprint 144에서 `mark_queue_done()`이 `doc_raw`를 함께 쓰도록 고쳤지만, 그것은
**앞으로 수집할 문서**에만 적용된다. 이미 받아 둔 556건은 이 스크립트로 채운다.

무엇이 막혀 있었나 — `page_count`가 없으면 상세페이지 문서 뷰어가 전체 쪽수를 알 수
없어 페이지 이동 UI를 그릴 수 없다. `GET /api/v1/item/{id}`의 `documents[].page_count`가
전부 null인 이유가 이것이다.

안전성
-----------------------------------------------------------------------------
- **파일이 실제로 있고 0바이트가 아닌 것만** 기록한다(DB만 앞서가지 않게).
- 이미 `doc_raw` 행이 있는 (item, doc_type)은 건드리지 않는다(재실행 안전).
- `document_status` / `document_queue` / 파일은 **하나도 바꾸지 않는다** — 읽기만 한다.
- 지우는 동작이 없다.
"""
import io
import os
import sys
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.database import (  # noqa: E402
    get_connection, _sha256_file, _pdf_page_count, to_relative_storage_path,
)
from crawler.doc_paths import (  # noqa: E402
    CANONICAL_DOC_FILENAME, _PRIMARY_EXT, sanitize_path_segment, _doc_dir_path,
)
from api.constants import DocumentStatus  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DOCUMENT_ROOT = os.path.join(PROJECT_ROOT, "documents")


def _force_utf8_stdout():
    """콘솔 인코딩을 UTF-8 로 고정한다. **`__main__` 에서만 부른다.**

    ## 왜 모듈 최상단이면 안 되는가 (2026-09-04)

    예전에는 이 두 줄이 import 시점에 그냥 실행됐다. 그러면 **이 모듈을 import
    하는 것만으로 `sys.stdout` 이 교체된다.** 교체된 순간, 옛 스트림의 버퍼에
    쌓여 있던 출력은 아무도 flush 하지 않으므로 **통째로 사라진다.**

    실측(2026-09-04): `test_doc_path_safety.py` 가 경로 생성기 대조에 이 모듈을
    넣자 그 앞 §1~§6 의 출력이 화면에서 사라졌다. 검사는 전부 돌고 통과했는데
    보고만 없어져, 회귀 실행기의 단언 집계가 175 -> 122 로 떨어졌다.
    **검사 결과가 조용히 줄어드는 것**이라 이 저장소가 가장 경계하는 모양이다.

    이 저장소는 로그 핸들러에 대해 이미 같은 규칙을 세워 두었다(BUGS #192 —
    `mvp_scraper.attach_file_log()` / `collect_documents.attach_file_log()` 는
    `__main__` 안에서만 부른다). stdout 도 같은 종류의 전역 자원이다.
    """
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")


def doc_file_path(court_name: str, case_no: str, item_no: str, doc_type: str):
    """`api/v1/documents.py`가 서빙하는 것과 **같은 경로**를 만든다.

    경로 규칙을 여기서 새로 쓰지 않고 `crawler/doc_paths.py`의 파일명 표를 그대로
    쓴다 — 규칙이 두 벌이 되면 백필이 뷰어와 다른 파일을 가리키게 된다.

    ★ 2026-08-17 Sprint 161: 조각 정규화도 `sanitize_path_segment()`로 맞췄다.
      파일명 표는 import 하면서 **정규화 규칙만 인라인으로 다시 쓰고 있었다** —
      바로 위 줄이 경계한 그 상태다. 옛 사본은 `/`만 치환해서 정본과 두 가지가 달랐다:

          역슬래시        Windows에서도 경로 구분자다. `a\b`가 오면 크롤러는 `a_b`에 쓰고
                         백필은 `a\b`를 계산해 **같은 문서를 두 경로로 본다**(BUGS #50/#64/#111 계열)
          "" / "." / ".." 정본은 `_`로 바꾼다. 옛 사본은 그대로 둬서 상위 디렉터리를 가리킬 수 있었다

      실데이터로 확인: `auction_item` 1,876행 + `document_status` 조인 5,628행,
      총 7,504개 조합에서 **옛 규칙과 새 규칙의 결과가 다른 경우 0건**이다
      (역슬래시 0건). 즉 기존 경로는 하나도 바뀌지 않는다.

    ★★ 2026-09-04: **디렉터리 조립도** 정본으로 모았다. Sprint 161 이 정규화만
      가져오고 `os.path.join(ROOT, court_name or "", ...)` 는 그대로 뒀는데,
      그 `or ""` 가 정확히 `repair_document_status.py` 에서 잡힌 것과 같은
      갈라짐이었다 — 실측(2026-09-04):

          _doc_dir_path(None, ...)   TypeError            (시끄럽게 죽는다)
          이 함수(None, ...)          <ROOT>/<사건>/<물건>  (조용히 **한 단계 위**)

      두 번째가 나쁘다. 예외도 안 나고 `DOCUMENT_ROOT` 안이라 담김 검사도 통과한다.
      그 경로에 우연히 파일이 있으면 이 스크립트가 **엉뚱한 파일의 해시·크기·쪽수**를
      그 물건의 `doc_raw` 로 적는다 — 뷰어의 쪽 이동이 그 값을 읽는다.

      `test_doc_path_safety.py` §7 의 docstring 이 이 파일을 이름으로 지목해
      *"Sprint 160 backfill_doc_raw.py 가 목록에 없어 또 살아남았다"* 라고 적어
      두었는데, 경로 생성기 대조 목록에도 여전히 빠져 있었다(세 번째다).
    """
    filename = CANONICAL_DOC_FILENAME.get((doc_type or "").upper())
    if not filename:
        return None
    # 규칙은 정본 하나뿐이다. 뿌리는 이 모듈 것을 준다 — 테스트가 모듈별로
    # `DOCUMENT_ROOT` 를 갈아 끼워 격리하기 때문이다(`_doc_dir_path` 의 `root` 주석).
    return os.path.join(
        _doc_dir_path(court_name, case_no, item_no or "1", root=DOCUMENT_ROOT),
        filename)


def primary_file_path(court_name: str, case_no: str, item_no: str, doc_type: str):
    """`doc_raw`에 기록할 대표 파일.

    STATUS는 html + json 두 개로 저장되는데, "수집 완료" 판정 기준 파일은 json이다
    (`doc_paths._PRIMARY_EXT`). 뷰어가 서빙하는 것은 html이라 둘이 다르다 —
    실체 메타데이터(해시/버전)는 완료 판정과 같은 파일을 기준으로 삼는 편이
    재수집 판정과 어긋나지 않는다.
    """
    key = (doc_type or "").lower()
    ext = _PRIMARY_EXT.get(key)
    if not ext:
        return None
    # 위 doc_file_path()와 같은 이유로 정본 함수를 쓴다 (Sprint 161 / 2026-09-04).
    return os.path.join(
        _doc_dir_path(court_name, case_no, item_no or "1", root=DOCUMENT_ROOT),
        key + "." + ext)


def plan(conn):
    """무엇을 쓸지 계산만 한다. 디스크/DB를 바꾸지 않는다."""
    rows = conn.execute(
        """
        SELECT ds.item_id, ds.doc_type, ds.status,
               ai.court_name, ai.case_no, ai.item_no
        FROM document_status ds
        JOIN auction_item ai ON ai.id = ds.item_id
        WHERE ds.status = ?
        ORDER BY ds.item_id, ds.doc_type
        """,
        (DocumentStatus.READY.value,),
    ).fetchall()

    existing = {(r["item_id"], r["doc_type"])
                for r in conn.execute("SELECT item_id, doc_type FROM doc_raw")}

    todo, already, missing, unsupported = [], 0, [], 0
    for r in rows:
        key = (r["item_id"], r["doc_type"])
        if key in existing:
            already += 1
            continue
        path = primary_file_path(r["court_name"], r["case_no"], r["item_no"], r["doc_type"])
        if not path:
            # 사진(IMAGE)처럼 doc_raw가 담당하지 않는 종류. 실패가 아니다.
            unsupported += 1
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            missing.append((r["item_id"], r["doc_type"], path))
            continue
        if size <= 0:
            missing.append((r["item_id"], r["doc_type"], path + " (0바이트)"))
            continue
        todo.append({"item_id": r["item_id"], "doc_type": r["doc_type"],
                     "path": path, "size": size})

    return {"todo": todo, "already": already, "missing": missing,
            "unsupported": unsupported, "ready_total": len(rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 doc_raw에 기록한다")
    args = ap.parse_args()

    conn = get_connection()
    try:
        p = plan(conn)
        print("=== doc_raw 백필 %s ===" % ("APPLY" if args.apply else "DRY-RUN"))
        print("  document_status READY          : %d" % p["ready_total"])
        print("  이미 doc_raw에 있음(건너뜀)     : %d" % p["already"])
        print("  doc_raw 대상 아님(사진 등)      : %d" % p["unsupported"])
        print("  기록 예정                       : %d" % len(p["todo"]))
        print("  READY인데 파일이 없다(문제)     : %d" % len(p["missing"]))
        for m in p["missing"][:20]:
            print("     MISSING item=%s %s %s" % m)

        if not args.apply:
            print("\n[DRY-RUN] 아무것도 쓰지 않았다.")
            print("반영하려면: python backfill_doc_raw.py --apply")
            return 0

        now = datetime.now().isoformat()
        today = datetime.now().strftime("%Y-%m-%d")
        written = 0
        pages_known = 0
        for t in p["todo"]:
            pc = _pdf_page_count(t["path"])
            if pc is not None:
                pages_known += 1
            conn.execute(
                """
                INSERT INTO doc_raw
                    (item_id, doc_type, storage_path, file_hash, file_size,
                     doc_version, page_count, crawl_date, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (t["item_id"], t["doc_type"], to_relative_storage_path(t["path"]),
                 _sha256_file(t["path"]), t["size"], 1, pc, today, now),
            )
            written += 1
            if written % 100 == 0:
                print("  ... %d건" % written)
        conn.commit()

        print("\n[APPLIED] doc_raw %d행 기록 (그중 page_count 확보 %d행)" % (written, pages_known))
        left = len(plan(conn)["todo"])
        print("반영 후 남은 대상: %d건" % left)
        return 0 if left == 0 else 1
    finally:
        conn.close()


if __name__ == "__main__":
    _force_utf8_stdout()
    sys.exit(main())
