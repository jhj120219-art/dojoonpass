"""자산(사진/문서) 기록과 디스크 실체가 어긋난 곳을 찾는다. **읽기 전용.**

## 왜 이 스크립트가 있나

이 저장소의 자산 결함은 전부 한 문장이다 — *"근거 둘이 갈라졌다."*

    BUGS #113  수집 결과엔 지문이 있는데 비교 대상(디스크)을 안 봤다
    BUGS #114  디스크는 줄었는데 DB를 지웠다(부분 수집인데)
    BUGS #120  형식이 바뀌자 디스크에 같은 순번이 둘이 됐다
    BUGS #127  DB는 줄었는데 디스크가 안 줄었다
    BUGS #128  법원은 0장인데 DB/디스크가 그대로였다
    BUGS #129  완료 기준은 json 인데 서빙은 html 이었다

`test_asset_pipeline.py` 5-I 가 **파이프라인 로직**에 대해 이 불변식을 건다. 그러나
로직이 맞아도 **운영 데이터**는 과거의 결함·수동 조작·중단된 실행 때문에 어긋나 있을 수
있다. 그 어긋남은 조용하다 — 화면은 READY 인데 열면 404 이거나, 아무도 안 보는 파일이
디스크를 먹는다. 이 스크립트는 그것을 **한 번에 드러낸다.**

## 절대 고치지 않는다

읽기만 한다(`mode=ro`). 무엇을 지우고 무엇을 다시 받을지는 상황마다 다르고, 잘못 지우면
되돌릴 수 없다. 이 저장소의 `*_dryrun.py` 관례를 따른다 — **발견과 조치는 분리한다.**

## 종료 코드

    0   어긋남 없음
    1   어긋남 발견 (상세는 표준출력)
    2   실행 자체가 실패 (DB 없음 등)

배치/스케줄러가 종료 코드만 보고도 판단할 수 있어야 한다 — 이 저장소가 BUGS #47 이래
지켜 온 규칙이다(출력 문구가 아니라 종료 코드를 근거로 쓴다).

    python audit_asset_integrity.py
"""
import contextlib
import datetime
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler.doc_paths import DOC_REQUIRED_FILES, _doc_dir_path
from crawler.image_assets import list_stored_images
import storage.database as _db

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SAMPLE = 8          # 각 항목당 출력할 예시 개수


def db_path():
    """지금 이 순간의 `storage.database.DB_PATH`.

    ★ `from storage.database import ...` 로 **값을 복사해 오면 안 된다** —
      그 순간의 스냅숏이라, 나중에 누가 경로를 바꿔도 여기는 옛 경로를 계속 본다
      (테스트가 스크래치 DB 를 가리켜도 실 DB 를 읽는다 — 실제로 그렇게 한 번
      틀렸고, 감사 결과가 통째로 무의미해졌다). 모듈을 통해 **매번 읽는다.**
    """
    return _db.DB_PATH


def _document_root():
    """지금 이 순간의 `crawler.doc_paths.DOCUMENT_ROOT`.

    `db_path()` 와 같은 이유로 값을 복사해 오지 않는다 — 테스트/자체검사가 임시 루트를
    가리켜도 여기가 옛 경로를 보면 감사가 통째로 무의미해진다.
    """
    import crawler.doc_paths as _dp
    return _dp.DOCUMENT_ROOT


def _download_root():
    """지금 이 순간의 `crawler.doc_paths.DOWNLOAD_DIR` (값을 복사해 두지 않는다)."""
    import crawler.doc_paths as _dp
    return _dp.DOWNLOAD_DIR


def _connect():
    """읽기 전용으로만 연다 — 이 스크립트가 무언가를 바꿀 여지 자체를 없앤다."""
    uri = "file:%s?mode=ro" % db_path().replace("\\", "/")
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _head(title):
    print("")
    print(title)


# ---------------------------------------------------------------------------
# selftest 출력이 실제 감사 결과처럼 보이는 문제 (2026-08-18 Sprint 212)
#
# selftest 는 **가짜 DB 에 결함을 일부러 심고** 같은 감사 함수를 돌린다. 그런데 그
# 출력이 실제 감사와 글자 하나 다르지 않아서, 실제로 오독이 일어났다 —
# 이 세션에서 selftest 의 "[3] READY 557개 / 부족 1개"를 **운영 실측으로 착각**해
# 있지도 않은 결함을 고치려 들었다(운영 실측은 556개 / 0개다).
#
# 감사기가 거짓 경보를 내는 것은 아무 경보도 안 내는 것만큼 나쁘다는 이 파일의 원칙이
# 자기 출력에도 적용된다. 심은 결함의 출력은 **눈에 띄게 다르게** 찍는다.
# ---------------------------------------------------------------------------
class _PrefixedOut:
    def __init__(self, stream, prefix):
        self._s, self._p, self._start = stream, prefix, True

    def write(self, text):
        for part in text.splitlines(True):
            if self._start and part.strip():
                self._s.write(self._p)
            self._s.write(part)
            self._start = part.endswith(chr(10))
        return len(text)

    def flush(self):
        self._s.flush()


@contextlib.contextmanager
def _scratch_output(label="[selftest 가짜DB] "):
    """이 블록 안의 출력은 운영 감사 결과가 아니라는 표시를 매 줄에 붙인다."""
    saved = sys.stdout
    sys.stdout = _PrefixedOut(saved, label)
    try:
        yield
    finally:
        sys.stdout = saved


def stray_image_files(keys):
    """사진 폴더 안에서 **이름 규칙에 맞지 않는 파일** 목록. 자체 검사가 직접 부른다.

    `list_stored_images()` 는 이런 파일을 조용히 건너뛴다 — 지문 계산에 잡동사니를
    섞지 않기 위해서다(그 자체는 옳다). 그러나 그 결과 `01.jpg.tmp` 같은 잔재는
    [1]/[2] 어느 쪽에도 **보이지 않는다.** `_write_image_atomically()` 가
    `dest + ".tmp"` 에 쓰고 `os.replace()` 하므로, 그 사이에 프로세스가 죽으면
    (전원·OOM kill 등 except 로 잡을 수 없는 죽음) 정확히 그 잔재가 남는다.
    여기서 세지 않으면 "없다"가 아니라 **"못 봤다"** 인데 보고서는 둘을 구별하지 못한다.
    """
    from crawler.image_assets import _image_dir_path, ALLOWED_IMAGE_EXTS
    out = []
    for key in keys:
        idir = _image_dir_path(*key)
        if not os.path.isdir(idir):
            continue
        for name in sorted(os.listdir(idir)):
            if not os.path.isfile(os.path.join(idir, name)):
                continue
            stem, dot, ext = name.rpartition(".")
            if dot and ext.lower() in ALLOWED_IMAGE_EXTS and stem.isdigit():
                continue
            out.append(os.path.join(*key) + os.sep + name)
    return out


def audit_images(conn):
    """auction_image 행 <-> 디스크 파일.

    ★ migration 020 미적용 DB 를 대상으로 돌 수 있다 — `api/v1/item.py` /
      `images.py` / `thumbnails.py` 가 이미 이 상태를 "사진 없음"으로 우아하게
      내려받는 것과 같은 이유다. 여기만 그 방어가 없어서 감사기가 통째로 죽고
      있었다 — 종료코드도 문서가 약속한 2(실행 자체 실패)가 아니라 파이썬
      기본 1(uncaught exception)이라 "어긋남 발견"과 구별되지 않았다.

      ★ 2026-08-25 정정 — 이 주석은 원래 "2026-08-24 실측: 이 저장소의 운영
      `auction.db` 자체가 지금 이 상태다"라고 적었다. **사실이 아니다** — 운영 DB 는
      020 이 2026-08-17 에 적용돼 있고 `auction_image` 45행이 실재하며 디스크 파일과의
      어긋남도 0건이다(docs/BUGS.md #185). 그 측정은 pre-020 백업 파일을 잸 것으로 보인다.
      방어 코드 자체는 그대로 유효하다 — 부트스트랩 직후의 새 DB 나, 백업을
      `DB_PATH` 로 지정해 감사기를 돌리는 경우가 실제로 있다.
    """
    table_missing = False
    try:
        rows = conn.execute("""
            SELECT ai.id AS item_id, ac.court_code, ai.case_no, ai.item_no,
                   img.seq, img.storage_path
            FROM auction_image img
            JOIN auction_item ai ON img.item_id = ai.id
            JOIN auction_case ac ON ai.case_id = ac.id
        """).fetchall()
    except sqlite3.OperationalError as e:
        if "no such table: auction_image" not in str(e):
            raise
        # 행이 전혀 없는 것과 같은 모양으로 다룬다 - 아래 [2] 의 disk-vs-DB
        # 비교는 여전히 유효하다(테이블이 없으면 모든 물건의 DB 쪽 집합이
        # 공집합이라는 뜻이고, 디스크에 파일이 있다면 그것 자체가 진짜 신호다).
        table_missing = True
        rows = []

    # (1) DB 가 가리키는 파일이 없다 -> 화면은 있다는데 열면 404
    missing = [r for r in rows
               if not r["storage_path"]
               or not os.path.isfile(os.path.join(PROJECT_ROOT, r["storage_path"]))]

    by_item = {}
    for r in rows:
        key = (r["court_code"], r["case_no"], str(r["item_no"]))
        by_item.setdefault(key, set()).add(r["seq"])

    # (2) 디스크에만 있는 순번 -> 고아 파일. 그리고 지문 공식이 갈라진다(BUGS #120/#127)
    items = conn.execute("""
        SELECT ac.court_code, ai.case_no, ai.item_no
        FROM auction_item ai JOIN auction_case ac ON ai.case_id = ac.id
    """).fetchall()
    divergent = []
    orphan_count = 0
    # ★ `list_stored_images()` 가 **이름 규칙에 안 맞는 파일을 조용히 건너뛴다**
    #   (2026-08-19 Sprint 217). 그 자체는 옳다 — 지문 계산에 잡동사니를 섞으면 안 된다.
    #   그러나 그 결과 `01.jpg.tmp` 같은 잔재는 [1]/[2] 어느 쪽에도 **보이지 않는다.**
    #   `_write_image_atomically()` 가 `dest + ".tmp"` 에 쓰고 `os.replace()` 하므로,
    #   그 사이에 프로세스가 죽으면(전원·OOM kill 등 except 로 잡을 수 없는 죽음)
    #   정확히 그 잔재가 남는다. 여기서 세지 않으면 "없다"가 아니라 **"못 봤다"** 인데
    #   보고서는 둘을 구별하지 못한다 — 이 저장소가 지키기로 한 규칙의 반대다.
    stray_in_images = stray_image_files(
        [(it["court_code"], it["case_no"], str(it["item_no"])) for it in items])
    for it in items:
        key = (it["court_code"], it["case_no"], str(it["item_no"]))
        disk = {x["seq"] for x in list_stored_images(*key)}
        db = by_item.get(key, set())

        if not disk and not db:
            continue
        if disk != db:
            divergent.append((key, sorted(db), sorted(disk)))
            orphan_count += len(disk - db)

    _head("[1] auction_image -> 파일")
    if table_missing:
        print("    auction_image 테이블이 없다(migration 020 미적용) - 사진 레코드 감사를 건너뛴다")
    print("    행 %d개 / 파일이 없는 행 %d개" % (len(rows), len(missing)))
    for r in missing[:SAMPLE]:
        print("      %s %s-%s seq=%s  %s"
              % (r["court_code"], r["case_no"], r["item_no"], r["seq"],
                 r["storage_path"]))

    _head("[2] 디스크 <-> auction_image 순번 집합")
    print("    어긋난 물건 %d개 / 고아 파일 %d개" % (len(divergent), orphan_count))
    for key, db, disk in divergent[:SAMPLE]:
        print("      %s  DB=%s  디스크=%s" % ("/".join(key), db, disk))

    _head("[2-b] 사진 폴더의 이름 규칙 밖 파일 (.tmp 잔재 등)")
    print("    %d개" % len(stray_in_images))
    for f in stray_in_images[:SAMPLE]:
        print("      %s" % f)
    if stray_in_images:
        print("      -> 지문 계산과 서빙은 이 파일들을 무시한다."
              " 즉 '없다'가 아니라 '안 보인다'였다. 정리는 승인 영역.")

    return len(missing) + len(divergent) + len(stray_in_images)


def audit_documents(conn):
    """document_status READY <-> 필요한 파일 전부 / doc_raw <-> 파일."""
    ready = conn.execute("""
        SELECT ac.court_code, ai.case_no, ai.item_no, ds.doc_type
        FROM document_status ds
        JOIN auction_item ai ON ds.item_id = ai.id
        JOIN auction_case ac ON ai.case_id = ac.id
        WHERE ds.status = 'READY' AND ds.doc_type <> 'IMAGE'
    """).fetchall()

    broken = []
    for r in ready:
        key = (r["doc_type"] or "").lower()
        if key not in DOC_REQUIRED_FILES:
            continue
        d = _doc_dir_path(r["court_code"], r["case_no"], str(r["item_no"]))
        for name in DOC_REQUIRED_FILES[key]:
            f = os.path.join(d, name)
            if not (os.path.isfile(f) and os.path.getsize(f) > 0):
                broken.append((r["court_code"], r["case_no"], r["item_no"],
                               r["doc_type"], name))
                break

    _head("[3] document_status READY -> 필요한 파일 전부 존재")
    print("    READY 문서 %d개 / 파일이 모자란 것 %d개" % (len(ready), len(broken)))
    for b in broken[:SAMPLE]:
        print("      %s %s-%s %s (없음: %s)" % b)

    raws = conn.execute("""
        SELECT dr.storage_path, dr.doc_type, ai.case_no, ai.item_no
        FROM doc_raw dr JOIN auction_item ai ON dr.item_id = ai.id
    """).fetchall()
    raw_missing = [r for r in raws
                   if r["storage_path"]
                   and not os.path.isfile(os.path.join(PROJECT_ROOT,
                                                       r["storage_path"]))]
    _head("[4] doc_raw -> 파일")
    print("    행 %d개 / 파일이 없는 행 %d개" % (len(raws), len(raw_missing)))
    for r in raw_missing[:SAMPLE]:
        print("      %s %s-%s  %s"
              % (r["doc_type"], r["case_no"], r["item_no"], r["storage_path"]))

    # ★ [4-b] 세 번째 방향 — **화면은 READY 인데 실체 기록(doc_raw)이 없다**
    #   (2026-08-19 Sprint 217, BUGS #144).
    #
    #   [3] 은 READY -> 파일, [4] 는 doc_raw -> 파일을 본다. 둘 다 통과하면서도
    #   **doc_raw 행 자체가 없는** 상태가 존재할 수 있고, 실제로 그것이 BUGS #144 다:
    #   "이미 존재. 스킵" 경로가 `files_saved=[]` 로 돌아와 `_record_doc_raw()` 가
    #   맨 앞에서 반환했다. 파일도 있고 화면도 READY 라 [3]/[4] 어느 쪽도 안 걸린다.
    #
    #   사용자에게는 `page_count`/`file_size`/`doc_version` 이 영원히 null 로 보인다
    #   (프런트가 쪽수 null 이면 페이지 이동 UI 를 그리지 않는다).
    no_raw = conn.execute("""
        SELECT ac.court_code, ai.case_no, ai.item_no, ds.doc_type
        FROM document_status ds
        JOIN auction_item ai ON ds.item_id = ai.id
        JOIN auction_case ac ON ai.case_id = ac.id
        WHERE ds.status = 'READY' AND ds.doc_type <> 'IMAGE'
          AND NOT EXISTS (SELECT 1 FROM doc_raw dr
                          WHERE dr.item_id = ds.item_id
                            AND dr.doc_type = ds.doc_type)
    """).fetchall()
    _head("[4-b] READY 인데 doc_raw 행이 없다 (BUGS #144)")
    print("    %d개" % len(no_raw))
    for r in no_raw[:SAMPLE]:
        print("      %s %s-%s %s" % (r["court_code"], r["case_no"], r["item_no"],
                                     r["doc_type"]))
    if no_raw:
        print("      -> 화면은 열람 가능인데 쪽수/크기/버전이 영원히 null 이다."
              " 재수집(overwrite)만이 벗어나는 길이다.")

    return len(broken) + len(raw_missing) + len(no_raw)


def audit_document_orphans(conn):
    """디스크 -> DB 방향: **대응하는 물건이 없는 문서 파일**이 있는가.

    2026-08-18 Sprint 193. [1]~[4] 는 전부 **DB 를 기준으로** 파일을 확인한다. 그 방향만
    보면 "아무도 가리키지 않는 파일"은 영원히 안 보인다 — 사진 쪽은 [2] 가 그 방향을
    보지만 문서 쪽에는 없었다.

    문서 고아가 생기는 경로:

        물건이 DB 에서 사라졌는데(재크롤 결과 등) 파일은 남았다
        경로 규칙이 바뀌기 전에 저장된 파일이 옛 경로에 남았다
        중단된 실행이 디렉터리만 만들었다

    화면에 잘못된 것을 보여 주지는 않는다(DB 를 근거로 서빙하므로). 그러나
    **디스크를 먹고, 전수 점검을 흐리고, 경로 규칙이 갈라졌다는 신호**일 수 있다.
    그래서 세기만 하고 지우지는 않는다.
    """
    # ★ 디렉터리 이름은 **정규화된** 값이다 — DB 의 원본 문자열과 그대로 비교하면 안 된다.
    #   실측(2026-08-18): `2008타경25092 / 2015타경19958`(중복사건) 같은 case_no 가 실제로
    #   있고, 디스크에는 `2008타경25092 _ 2015타경19958` 로 저장된다.
    #   정규화를 빼먹었더니 **정상 디렉터리 37개가 "고아"로 잡혔다** — 감사기가 거짓
    #   경보를 내는 것은 아무 경보도 안 내는 것만큼 나쁘다(다음부터 아무도 안 본다).
    #   쓰는 쪽과 **같은 함수**를 쓴다(규칙을 베끼지 않는다 — Sprint 146 의 교훈).
    from crawler.doc_paths import sanitize_path_segment

    known = set()
    for r in conn.execute("""
        SELECT ac.court_code, ai.case_no, ai.item_no
        FROM auction_item ai JOIN auction_case ac ON ai.case_id = ac.id
    """):
        known.add((r["court_code"],
                   sanitize_path_segment(r["case_no"]),
                   sanitize_path_segment(str(r["item_no"]))))

    doc_names = {n for names in DOC_REQUIRED_FILES.values() for n in names}

    unknown_items = []
    stray_files = []
    empty_dirs = 0
    root = _document_root()
    if os.path.isdir(root):
        for court in sorted(os.listdir(root)):
            cp = os.path.join(root, court)
            if not os.path.isdir(cp):
                continue
            for case in sorted(os.listdir(cp)):
                kp = os.path.join(cp, case)
                if not os.path.isdir(kp):
                    continue
                for item in sorted(os.listdir(kp)):
                    ip = os.path.join(kp, item)
                    if not os.path.isdir(ip):
                        continue
                    files = [f for f in os.listdir(ip) if os.path.isfile(
                        os.path.join(ip, f))]
                    has_images = os.path.isdir(os.path.join(ip, "images")) and \
                        os.listdir(os.path.join(ip, "images"))
                    if not files and not has_images:
                        empty_dirs += 1
                        continue
                    if (court, case, item) not in known:
                        unknown_items.append((court, case, item, len(files)))
                        continue
                    for f in files:
                        if f not in doc_names:
                            stray_files.append(os.path.join(court, case, item, f))

    _head("[6] 디스크 -> DB: 대응 물건이 없는 문서 파일")
    print("    대응 물건이 없는 디렉터리 %d개 / 이름 규칙 밖 파일 %d개 / 빈 디렉터리 %d개"
          % (len(unknown_items), len(stray_files), empty_dirs))
    for u in unknown_items[:SAMPLE]:
        print("      %s/%s/%s  파일 %d개" % u)
    for f in stray_files[:SAMPLE]:
        print("      규칙 밖: %s" % f)
    if empty_dirs:
        print("      (빈 디렉터리는 결함으로 세지 않는다 - 조회가 만든 흔적,"
              " 정리는 승인 영역)")

    return len(unknown_items) + len(stray_files)


def audit_queue_vs_status(conn):
    """큐가 done 인데 화면은 미완료 / 큐는 대기인데 화면은 READY."""
    rows = conn.execute("""
        SELECT dq.status AS q, ds.status AS s, COUNT(*) AS n
        FROM document_queue dq
        JOIN auction_case ac ON ac.court_code = dq.court_code
                            AND ac.case_no = dq.case_no
        JOIN auction_item ai ON ai.case_id = ac.id AND ai.item_no = dq.item_no
        JOIN document_status ds ON ds.item_id = ai.id
                               AND ds.doc_type = UPPER(dq.doc_type)
        WHERE (dq.status = ? AND ds.status NOT IN ('READY', 'NO_IMAGE'))
           OR (dq.status IN (?, ?) AND ds.status = 'READY')
        GROUP BY dq.status, ds.status
    """, (_db.QUEUE_STATUS_DONE, _db.QUEUE_STATUS_PENDING,
          _db.QUEUE_STATUS_REFRESH)).fetchall()

    _head("[5] document_queue <-> document_status")
    if not rows:
        print("    어긋남 없음")
        return 0
    for r in rows:
        print("      큐=%s 화면=%s : %d행" % (r["q"], r["s"], r["n"]))
    # ★ 'pending + READY' 는 **정상**일 수 있다 — 재수집 대기 중인 문서는 여전히
    #   보여 줄 수 있다(BUGS #122 의 결정). 그래서 건수만 보고하고 결함으로 세지 않는다.
    return sum(r["n"] for r in rows
               if r["q"] == "done" and r["s"] not in ("READY", "NO_IMAGE"))


def selftest():
    """이 감사기가 **실제로 어긋남을 잡는지** 스스로 확인한다. 운영 DB 는 건드리지 않는다.

    ## 왜 감사기가 자기를 검사하나

    감사 스크립트는 조용히 눈이 멀기 쉽다 — 쿼리가 바뀌거나 경로 규칙이 달라지면
    "어긋남 없음"을 계속 찍으면서 아무것도 안 보게 된다. 그리고 그 상태는 **정상과
    겉으로 완전히 같다.** 그래서 결함을 일부러 심어 잡히는지 확인한다.

    ## 왜 검사 내용이 회귀 스위트가 아니라 여기 있나

    원래 이유는 이랬다: *"이 파일은 아직 **미추적 파일**이고(`git add` 는 승인 영역),
    추적된 테스트가 미추적 파일을 import 하면 커밋 시 부팅이 깨진다(BUGS #105).
    파일이 추적되면 그때 회귀 스위트로 옮기는 것이 맞다."*

    ★ 2026-08-24 갱신 — 이 파일은 **이미 추적된다**(`git ls-files` 실측). 그래서 그
      조건이 스스로 말한 대로 충족됐다. 다만 검사 **내용**은 여기 그대로 둔다 —
      심는 결함이 이 파일의 경로 규칙·쿼리와 한 몸이라 떼면 곧 갈라진다.
      대신 `test_audit_selftests.py` 가 이 `--selftest` 를 **회귀 스위트에서 실제로
      실행**한다(import 가 아니라 서브프로세스 + 종료코드 계약). 그 전까지는 이
      selftest 를 돌리는 것이 저장소 어디에도 없었다 — 감사기가 눈이 멀어도
      아무도 모르는 상태였고, 그것은 이 파일이 막으려던 상태 그 자체다.

        python audit_asset_integrity.py --selftest
    """
    import shutil
    import tempfile

    print("=" * 70)
    print(" 감사기 자체 검사 (스크래치 사본, 운영 DB 무변경)")
    print("=" * 70)

    if not os.path.exists(db_path()):
        print("  원본 DB 가 없어 자체 검사를 할 수 없다: %s" % db_path())
        return 2

    failures = []

    def check(name, actual, expected):
        ok = actual == expected
        print("  [%s] %s: %r (기대 %r)" % ("PASS" if ok else "FAIL", name,
                                           actual, expected))
        if not ok:
            failures.append(name)

    tmp = tempfile.mkdtemp(prefix="audit_selftest_")
    scratch = os.path.join(tmp, "auction.db")
    # 온라인 백업 스냅샷 - 워커가 쓰는 중이어도 일관된 사본을 만든다
    # (shutil.copy2 는 찢어질 수 있다. 사유: storage/database.py:snapshot_live_db)
    _db.snapshot_live_db(scratch)
    saved = _db.DB_PATH
    _db.DB_PATH = scratch
    try:
        # 기준선 — 사본은 원본과 같으므로 어긋남이 없어야 한다.
        conn = _connect()
        try:
            with _scratch_output():
                base = (audit_images(conn) + audit_documents(conn)
                        + audit_queue_vs_status(conn))
        finally:
            conn.close()
        check("사본 기준선은 어긋남 0", base, 0)

        # 결함 A — DB 는 있는데 파일이 없다
        #
        # ★ 심는 행의 item_id 를 **`auction_item` 에서** 가져온다 (2026-08-25).
        #   예전에는 `SELECT ... FROM auction_image LIMIT 1` 이었다. 즉 **사진이 이미
        #   수집돼 있어야만** 결함을 심을 수 있었다. 사진이 0행이면 INSERT 가 0행을 쓰고,
        #   `audit_images()` 는 당연히 0 을 돌려주며, 이 검사는 "감사기가 눈이 멀었다"가
        #   아니라 **아무것도 심지 못했다**는 이유로 붉어진다 — 실제로 그렇게 됐다
        #   (2026-08-25: `auction_image` 0행, migration 020 미적용 상태에서는 아예
        #   `no such table` 로 죽었다).
        #
        #   이 파일의 존재 이유가 "감사기가 눈이 멀어도 아무도 모르는 상태"를 막는 것인데,
        #   그 자기 검증이 **운영 데이터의 우연한 내용에 의존**하고 있었다. 사진 수집은
        #   승인 영역(데스크탑1)이라 이 머신에서는 영원히 채워지지 않는다.
        #   `auction_item` 은 이 감사기가 도는 어떤 DB 에도 반드시 있다(없으면 아래
        #   check 가 그것을 먼저 말한다).
        c = sqlite3.connect(scratch)
        try:
            seed = c.execute("SELECT id FROM auction_item LIMIT 1").fetchone()
            if seed:
                c.execute("""INSERT INTO auction_image
                    (item_id, seq, kind, storage_path, file_hash, file_size,
                     crawl_date, created_at)
                    VALUES (?, 9999, 'QA', 'documents/qa/none/1/images/9999.jpg',
                            'h', 1, '2026-01-01', '2026-01-01')""", (seed[0],))
                c.commit()
        finally:
            c.close()
        check("결함 A 를 심을 물건이 있다(검사가 공허하지 않다)", bool(seed), True)
        conn = _connect()
        try:
            with _scratch_output():
                found = audit_images(conn)
        finally:
            conn.close()
        check("파일 없는 사진 행을 잡는다", found > 0, True)

        # 결함 B — 문서가 READY 인데 파일이 없다
        c = sqlite3.connect(scratch)
        try:
            c.execute("""UPDATE document_status SET status='READY'
                         WHERE doc_type='SPEC' AND status <> 'READY'
                         AND item_id IN (SELECT item_id FROM document_status
                                         WHERE doc_type='SPEC' AND status <> 'READY'
                                         LIMIT 1)""")
            changed = c.total_changes
            c.commit()
        finally:
            c.close()
        if changed:
            conn = _connect()
            try:
                with _scratch_output():
                    found_doc = audit_documents(conn)
            finally:
                conn.close()
            check("READY 인데 파일 없는 문서를 잡는다", found_doc > 0, True)
        else:
            print("  [SKIP] READY 로 바꿀 비-READY SPEC 행이 없다(결함 B 미검증)")

        # 결함 C — READY + 파일도 있는데 doc_raw 행만 없다 (BUGS #144 의 모양)
        #   [3]/[4] 는 통과하고 [4-b] 만 걸려야 한다. 그래서 삭제 **전후 차이**를 본다.
        c = sqlite3.connect(scratch)
        try:
            row = c.execute("""
                SELECT dr.item_id, dr.doc_type FROM doc_raw dr
                JOIN document_status ds ON ds.item_id = dr.item_id
                                       AND ds.doc_type = dr.doc_type
                WHERE ds.status = 'READY' LIMIT 1""").fetchone()
            if row:
                c.execute("DELETE FROM doc_raw WHERE item_id=? AND doc_type=?", row)
                c.commit()
        finally:
            c.close()
        if row:
            conn = _connect()
            try:
                with _scratch_output():
                    after = audit_documents(conn)
            finally:
                conn.close()
            # 결함 B 가 이미 심어져 있을 수 있으므로 **증가분**으로 판정한다.
            check("READY 인데 doc_raw 가 없는 문서를 잡는다",
                  after > (found_doc if changed else base), True)
        else:
            print("  [SKIP] READY + doc_raw 인 행이 없다(결함 C 미검증)")

        # 결함 D — 사진 폴더의 `.tmp` 잔재를 보는가 (2026-08-19 Sprint 217).
        #   운영 `documents/` 는 절대 건드리지 않는다 — **임시 루트**를 만들어
        #   거기에만 심고, 두 모듈의 DOCUMENT_ROOT 를 함께 갈아 끼운다
        #   (`image_assets` 와 `doc_paths` 가 각자 갖고 있다 — 하나만 바꾸면
        #    조회는 임시 루트, 판정은 운영 루트가 되어 검사가 무의미해진다).
        import crawler.doc_paths as _dp
        import crawler.image_assets as _ia
        fake_root = os.path.join(tmp, "documents")
        key = ("QA법원", "2026타경1", "1")
        os.makedirs(os.path.join(fake_root, *key) + os.sep + "images")
        with open(os.path.join(fake_root, *key, "images", "01.jpg.tmp"), "wb") as fh:
            fh.write(b"x" * 10)
        with open(os.path.join(fake_root, *key, "images", "01.jpg"), "wb") as fh:
            fh.write(b"x" * 10)
        saved_roots = (_dp.DOCUMENT_ROOT, _ia.DOCUMENT_ROOT)
        _dp.DOCUMENT_ROOT = _ia.DOCUMENT_ROOT = fake_root
        try:
            stray = stray_image_files([key])
            clean = list_stored_images(*key)
        finally:
            _dp.DOCUMENT_ROOT, _ia.DOCUMENT_ROOT = saved_roots
        check(".tmp 잔재를 잡는다", [os.path.basename(x) for x in stray],
              ["01.jpg.tmp"])
        check("정상 파일은 잔재로 세지 않는다", [x["seq"] for x in clean], [1])

        # 결함 E — [9] 가 **깨진 URL 을 실제로 잡는가** (2026-08-19 Sprint 217).
        #   운영 서버를 쓰지 않는다. 상세는 200 으로 주면서 사진 URL 만 404 로 주는
        #   **가짜 서버**를 세워 대조한다. 서버가 없을 때 0 을 돌려주는 경로와
        #   깨진 URL 을 잡는 경로가 **서로 다르다는 것**이 여기서 증명된다.
        import http.server
        import json as _json
        import threading

        class _Fake(http.server.BaseHTTPRequestHandler):
            def do_GET(self):                      # noqa: N802 - stdlib 규약
                if self.path.startswith("/api/v1/search"):
                    body = b"{}"
                elif "/images/" in self.path:
                    self.send_response(404)
                    self.end_headers()
                    return
                else:
                    body = _json.dumps({
                        "images": [{"seq": 1, "url": "/api/v1/item/1/images/1"}],
                        "image_count": 1, "images_status": "READY",
                        "documents": [],
                    }).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):             # 조용히
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), _Fake)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        try:
            conn = _connect()
            try:
                with _scratch_output():
                    broken = audit_api_promises(conn, base)
                    unreachable = audit_api_promises(conn, "http://127.0.0.1:1")
            finally:
                conn.close()
        finally:
            srv.shutdown()
        check("[9] 가 열리지 않는 사진 URL 을 잡는다", broken > 0, True)
        check("[9] 는 서버가 없으면 '확인하지 못함'(어긋남 0)", unreachable, 0)

        # 결함 E-2 — 429 를 **결함으로 세지 않는가** (2026-09-01).
        #   위 _Fake 는 사진 URL 에 404 를 준다. 여기서는 같은 자리에 **429** 를 준다.
        #   404 는 결함(위 검사), 429 는 미확인이어야 한다 — 둘이 같은 `HTTPError` 인데
        #   조치가 정반대라, 코드가 둘을 실제로 갈라 놓는지 여기서 증명한다.
        #   (이 구분이 없던 동안 운영 실행에서 213건이 거짓 결함으로 보고됐다.)
        class _Throttled(_Fake):
            def do_GET(self):                      # noqa: N802 - stdlib 규약
                if "/images/" in self.path:
                    self.send_response(429)
                    self.send_header("Retry-After", "0")
                    self.end_headers()
                    return
                _Fake.do_GET(self)

        srv2 = http.server.HTTPServer(("127.0.0.1", 0), _Throttled)
        th2 = threading.Thread(target=srv2.serve_forever, daemon=True)
        th2.start()
        try:
            conn = _connect()
            try:
                with _scratch_output():
                    throttled = audit_api_promises(
                        conn, "http://127.0.0.1:%d" % srv2.server_address[1])
            finally:
                conn.close()
        finally:
            srv2.shutdown()
        check("[9] 는 429 를 결함으로 세지 않는다(미확인)", throttled, 0)

        # 결함 E — [7] 의 "실제로 수집을 시도할 행" 분류 (2026-08-24 Sprint 251)
        #
        # 운영 데이터만으로는 이 분류를 검증할 수 없다. 지금 고아 대기 행은 12개인데
        # **전부 기일 경과**라, 옛 코드(전부를 낭비로 세던 것)와 새 코드(경과분을 빼는 것)를
        # 구별하려면 "기일이 남은 고아 행"이 있어야 한다. 그래서 여기서 만들어 넣는다.
        _rows = [
            {"status": "pending", "auction_date": "2026-07-30", "n": 3},   # 경과 -> 비용 0
            {"status": "pending", "auction_date": "2099-01-01", "n": 2},   # 남음 -> 실제 비용
            {"status": "refresh", "auction_date": None,         "n": 1},   # 날짜 없음 -> 방어선 통과
            {"status": "done",    "auction_date": "2026-07-14", "n": 3},   # 대기가 아니다
            {"status": "SKIPPED_EXPIRED", "auction_date": "2026-07-09", "n": 3},
        ]
        _t, _w, _live, _exp = classify_queue_orphans(_rows, "2026-08-24")
        check("[7] 고아 전체 수", _t, 12)
        check("[7] 대기(pending/refresh) 수", _w, 6)
        check("★ [7] 기일이 남은 것만 '실제로 수집한다'로 센다", _live, 3)
        check("[7] 기일 경과분은 비용에서 뺀다", _exp, 3)
    finally:
        _db.DB_PATH = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    if failures:
        print(" 자체 검사 실패 %d건: %s" % (len(failures), ", ".join(failures)))
        return 1
    print(" 자체 검사 통과 - 감사기가 실제로 어긋남을 잡는다")
    return 0


def classify_queue_orphans(rows, today):
    """고아 큐 행을 (전체, 대기, 기일남음, 기일경과) 로 나눈다. 순수 함수 — DB 를 안 본다.

    쿼리에서 떼어 낸 이유는 하나다: **자체 검사가 이 분류를 직접 검증할 수 있어야 한다.**
    운영 DB 에는 지금 "기일 남은 고아 행"이 하나도 없어서(전부 경과), 실제 데이터만으로는
    분류가 맞는지 확인할 수 없다 — 0을 0으로 세는 것은 공허하다.

    `expired` 판정은 워커의 2차 방어선과 **글자 그대로 같은 조건**이어야 한다
    (`doc_worker.py`: `if auction_date and auction_date < today`).
    날짜가 비어 있으면 그 방어선을 통과하므로 만료로 세지 않는다.
    """
    total = sum(r["n"] for r in rows)
    waiting = [r for r in rows if r["status"] in ("pending", "refresh")]
    waiting_n = sum(r["n"] for r in waiting)
    live_n = sum(r["n"] for r in waiting
                 if not (r["auction_date"] and r["auction_date"] < today))
    return total, waiting_n, live_n, waiting_n - live_n


def audit_queue_orphans(conn):
    """큐 -> 물건 방향: **대응하는 `auction_item` 이 없는 큐 행**이 있는가.

    2026-08-18 Sprint 193. 큐 행은 `(법원, 사건, 물건)` 문자열만 들고 있고
    `auction_item` 을 FK 로 참조하지 않는다(설계상 그렇다 — 크롤 시점에 물건이 아직
    없을 수 있다). 그래서 물건이 사라지거나 애초에 잘못된 키로 적재되면 **아무도 안
    가리키는 큐 행**이 남는다.

    왜 문제인가:

        pending 이고 **기일이 남아 있으면**
                       워커가 실제로 브라우저를 몰아 수집한다(물건당 약 22초).
                       그리고 `mark_queue_done()` 은 `document_status`/`doc_raw` 를
                       **쓰지 못한 채**(item_id 가 없다) 큐만 done 으로 닫는다.
                       = 시간과 법원 부하를 쓰고, 파일은 고아로 남고, 기록은 안 남는다.
        pending 이지만 **기일이 지났으면**
                       비용이 없다. `doc_worker.py` 의 2차 방어선(`auction_date < today`)
                       이 브라우저를 열기 전에 `mark_queue_skipped_expired()` 로 종결한다.
                       고아 행은 `reconcile_queue_auction_date()` 가 대조할 물건 자체가
                       없어 큐 날짜를 그대로 돌려주므로, 정정으로 되살아나지도 않는다.
        done 이면      이미 그 일이 벌어진 뒤다. 디스크에 고아 문서가 남아 있다([6] 이 잡는다).

    ★ 2026-08-24 수정 — 이 감사기는 원래 pending/refresh 고아 행 **전부**를
      "워커가 실제로 수집을 시도할 대기 행"으로 셌다. 그 숫자는 기일 방어선을 빼먹은
      것이라 실제보다 크다. 실측(2026-08-24): 고아 18행 중 pending 12행이지만 **12행
      전부 기일 경과**(가장 늦은 것이 2026-07-30)라 실제로 수집을 시도할 행은 **0행**이다.
      같은 저장소의 `test_pipeline_integrity.py` 고아 상한 주석은 이미 "낭비 비용은
      지금은 0"이라고 적고 있었다 — 두 도구가 서로 다른 말을 하고 있었다.
      **왜 중요한가**: 이 숫자는 사람이 "고아 정리를 지금 해야 하나"를 판단하는 근거다.
      부풀려진 비용은 승인 영역의 파괴적 삭제를 서두르게 만든다.

    실측(2026-08-18): 고아 6물건 x 3종 = **18행**. 그중 `2024타경2803` 은 같은 사건번호가
    **두 법원에 존재**하는 경우였다 — 고양지원(고아, 문서 12.7MB 수집됨) / 춘천지방법원
    (실제 물건, 큐는 pending). 법원을 식별키에 넣는 문제(BUGS #14/#18/#103/#107)의 잔재다.

    **사용자에게 보이는 피해는 없다** — 서빙은 `auction_item` 을 근거로 하므로 고아 쪽
    경로는 조회되지 않는다. 정리는 `cleanup_orphans_dryrun.py` 가 담당한다(삭제는 승인 영역).
    """
    today = datetime.date.today().isoformat()
    rows = conn.execute("""
        SELECT dq.court_code, dq.case_no, dq.item_no, dq.status, dq.auction_date,
               COUNT(*) AS n
        FROM document_queue dq
        LEFT JOIN auction_case ac ON ac.court_code = dq.court_code
                                 AND ac.case_no = dq.case_no
        LEFT JOIN auction_item ai ON ai.case_id = ac.id AND ai.item_no = dq.item_no
        WHERE ai.id IS NULL
        GROUP BY dq.court_code, dq.case_no, dq.item_no, dq.status, dq.auction_date
        ORDER BY dq.status, dq.court_code
    """).fetchall()

    total, waiting_n, live_n, expired_n = classify_queue_orphans(rows, today)

    _head("[7] 큐 -> 물건: 대응 auction_item 이 없는 큐 행")
    print("    고아 큐 행 %d개" % total)
    print("      대기(pending/refresh) %d개 = 기일 남음 %d개 + 기일 경과 %d개"
          % (waiting_n, live_n, expired_n))
    print("      -> 워커가 실제로 브라우저를 여는 것은 **기일 남음 %d개**뿐이다"
          " (기일 경과분은 doc_worker 2차 방어선이 브라우저 없이 종결한다)" % live_n)
    for r in rows[:SAMPLE]:
        print("      %s %s-%s  %s x%d  (기일 %s)"
              % (r["court_code"], r["case_no"], r["item_no"], r["status"], r["n"],
                 r["auction_date"] or "없음"))
    if live_n:
        print("      -> 이 행들은 수집에 시간·법원 부하를 쓰지만 기록은 남지 않는다."
              " 정리는 cleanup_orphans_dryrun.py (삭제는 승인 영역)")
    elif total:
        print("      -> 지금 낭비되는 수집 비용은 **0**이다. 정리는 급하지 않다"
              " (남은 문제는 디스크 고아 파일뿐 - [6] 참고)")

    return total


def audit_orphan_downloads(conn):
    """다운로드 폴더에 **받아 놓고 목적지로 못 옮긴 파일**이 쌓였는가.

    2026-08-18 Sprint 201. 문서 수집은 `downloads/` 로 내려받은 뒤 `move_into_place()`
    로 물건 폴더에 옮긴다. 옮기지 못하면 파일은 그 폴더에 **영원히 남는다** — 아무도
    안 보고, 아무도 안 지운다.

    이것이 조용한 이유: 수집은 "실패"로 보고되고, 실패는 재시도로 이어지고, 재시도가
    또 받아서 또 남긴다. 화면에는 "수집 실패"만 보이므로 **파일이 실제로는 와 있었다는
    사실이 어디에도 드러나지 않는다.**

    실측(2026-08-18): 고아 PDF **8개 / 14.0MB**.
      - 감정평가서 3개 -> BUGS #135(탭이 안 뜨면 다운로드 확인도 안 하고 실패 처리)
        가 원인이었고 고쳤다.
      - 매각물건명세서 5개 -> 다른 경로다(파일이 30초 안에 안 왔다). 원인이 확정되지
        않아 여기서는 **탐지만 한다**(BUGS #136).

    지우지 않는다 — 어느 물건 것인지 파일 이름만으로는 확정할 수 없고(법원이 붙인
    이름이다), 잘못 옮기면 엉뚱한 물건에 남의 문서가 붙는다.
    """
    root = _download_root()
    files = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            full = os.path.join(root, name)
            if os.path.isfile(full):
                files.append((name, os.path.getsize(full)))

    total_mb = sum(sz for _n, sz in files) / 1024.0 / 1024.0
    _head("[8] 다운로드 폴더에 남은 고아 파일")
    print("    고아 %d개 / %.1f MB" % (len(files), total_mb))
    for name, sz in files[:SAMPLE]:
        print("      %9d B  %s" % (sz, name[:60]))
    if files:
        print("      -> 받아 놓고 목적지로 못 옮긴 것이다. 원인은 수집기 쪽이고,")
        print("         정리는 어느 물건 것인지 확정할 수 없어 여기서 하지 않는다.")

    return len(files)


def audit_api_promises(conn, api_base):
    """[9] **API 가 광고한 자산 URL 이 실제로 열리는가** (실서버 HTTP, 읽기 전용).

    2026-08-19 Sprint 217. [1]~[4] 는 DB 와 디스크만 본다. 그 둘이 맞아도
    **서빙 계층에서 어긋날 수 있다** — 경로 규칙이 갈라지거나(`api/v1/item.py` 의
    `_document_url()` 주석: "API 는 URL 을 주는데 그 URL 이 404"), 권한/헤더가
    막거나, 상태 판정이 실체와 다르거나.

    그래서 응답이 준 URL 을 **그대로 다시 요청한다.** 표본이 아니라 전수다.

    서버가 없으면 **"이상 없음"이 아니라 "확인하지 못함"** 으로 보고한다 —
    이 저장소가 지키기로 한 구분이다. 그때는 어긋남 수에 더하지 않되 그 사실을 남긴다.
    """
    import json as _json
    import time as _time
    import urllib.error
    import urllib.request

    # ★ 네트워크 계층 실패를 **세 번째 값**으로 돌려준다 (2026-08-25, docs/BUGS.md #194).
    #
    #   예전에는 `HTTPError` 만 잡았다. 그래서 읽는 도중 타임아웃/연결 리셋이 나면
    #   그대로 위로 새어 나가 **감사기 전체가 트레이스백으로 죽었다** - 앞서 찍은
    #   [1]~[8] 결과까지 판정 없이 버려진다. 실측(2026-08-25): 문서 URL 두 개에서
    #   19초 뒤 ConnectionResetError 가 나 이 함수가 그대로 터졌다.
    #
    #   "열리지 않았다"(결함)와 "이번에 확인하지 못했다"(미확인)는 조치가 정반대다.
    #   BUGS #188 이 `audit_auth_health.py` 에서 세운 구분을 여기서도 지킨다.
    # ★ 네트워크 계열 실패만 재시도한다. HTTP 오류는 재시도하지 않는다 -
    #   몇 번을 보내도 404 는 404 다. (BUGS #188 이 JWKS 에서 세운 것과 같은 규칙.)
    #
    #   재시도를 넣은 근거는 실측이다(2026-08-25). 이 감사는 자산 URL 601개를
    #   **연속으로** 요청하는데, 그중 16건이 15초 타임아웃으로 떨어졌다. 그 16개를
    #   그대로 다시 요청하니 **8/8 이 0.02~0.15초에 200** 이었다(표본 8개 전수).
    #   파일도 엔드포인트도 멀쩡하다는 뜻이다 - 빠른 연속 요청에서만 생기는
    #   연결 계층 현상으로 보이며, 원인은 미확정으로 남긴다(docs/BUGS.md #194).
    #   실제 브라우저는 연결을 재사용하므로 같은 조건이 아니다.
    GET_ATTEMPT_TIMEOUTS = (15, 25)

    # ★ 429 는 **404 와 다르다** (2026-09-01 실측).
    #
    #   위 주석은 "HTTP 오류는 재시도하지 않는다 - 몇 번을 보내도 404 는 404 다" 라고
    #   적어 두었고 그 말은 옳다. 그런데 `HTTPError` 를 **전부** 그렇게 다루는 바람에
    #   429(Too Many Requests) 까지 "서버가 대답했으니 판정할 수 있다" 로 새어 들어갔다.
    #
    #   실측: 이 감사는 자산 URL 을 전수로, 연속으로 요청한다(이번 실행은 물건 460개 /
    #   URL 926개). `api_server.py` 의 속도 제한은 기본 **분당 1200회**라 감사기가
    #   스스로 그 한도를 넘긴다. 그 결과 **213건이 "열리지 않음"으로 보고**됐다 —
    #   전부 429 였고, 그 자산들은 **한 번도 실제로 검사되지 않았다.**
    #   어긋남 23건이 236건으로 부풀어 진짜 결함이 그 옆에 묻혔다.
    #
    #   429 는 "이 자산이 깨졌다"가 아니라 "지금은 확인하지 못했다"이다 — 이 파일이
    #   이미 세워 둔 결함/미확인 구분(BUGS #188/#194)에서 **미확인 쪽**이다.
    #   그리고 404 와 달리 **재시도하면 달라진다.** 서버가 `Retry-After` 를 주므로
    #   (api_server.py 의 429 응답) 그 값을 그대로 지킨다.
    RATE_LIMIT_RETRIES = 4
    RATE_LIMIT_MAX_SLEEP = 65     # Retry-After 는 슬라이딩 창이라 최대 60초쯤이다

    def _get_once(path):
        """한 번의 왕복. (status, content-type, body, 실패사유, Retry-After)"""
        last = None
        for timeout in GET_ATTEMPT_TIMEOUTS:
            try:
                with urllib.request.urlopen(api_base + path, timeout=timeout) as r:
                    return r.status, r.headers.get("content-type", ""), r.read(), None, None
            except urllib.error.HTTPError as e:
                ra = e.headers.get("Retry-After") if e.headers else None
                return e.code, "", b"", None, ra   # 서버가 대답했다 - 판정할 수 있다
            except Exception as e:                # noqa: BLE001 - 못 닿은 것은 결함이 아니다
                last = "%s: %s" % (type(e).__name__, str(e)[:90])
        return None, "", b"", "%s (%d회 시도)" % (last, len(GET_ATTEMPT_TIMEOUTS)), None

    def get(path):
        """(status, content-type, body, 실패사유). 못 닿았으면 status 가 None 이다."""
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            st, ct, body, why, retry_after = _get_once(path)
            if st != 429:
                return st, ct, body, why
            if attempt < RATE_LIMIT_RETRIES:
                try:
                    # 서버가 준 값을 **그대로** 지킨다. 0 을 1 로 올리지 않는다 -
                    # 그러면 자기 검증(Retry-After: 0)이 URL 마다 몇 초씩 잔다.
                    wait = int(float(retry_after))
                except (TypeError, ValueError):
                    wait = 1          # 헤더가 없거나 이상하면 1초는 쉬어 준다
                _time.sleep(min(max(wait, 0), RATE_LIMIT_MAX_SLEEP))
        # 끝까지 throttle 이면 **판정하지 않는다**(어긋남으로 세지 않는다).
        return None, "", b"", "429 속도 제한 - %d회 시도 후에도 throttle" % (RATE_LIMIT_RETRIES + 1)

    _head("[9] API 가 광고한 자산 URL 이 실제로 열리는가 (%s)" % api_base)
    try:
        with urllib.request.urlopen(api_base + "/api/v1/search", timeout=5):
            pass
    except Exception as exc:  # noqa: BLE001 - 서버 부재는 결함이 아니라 미확인이다
        print("    ** 확인하지 못함 ** - 서버에 연결할 수 없다 (%s)" % exc)
        print("       띄운 뒤 다시: python -m uvicorn api_server:app --port 8000")
        return 0

    ids = [r[0] for r in conn.execute("""
        SELECT DISTINCT item_id FROM auction_image
        UNION SELECT DISTINCT item_id FROM doc_raw
        UNION SELECT DISTINCT item_id FROM document_status WHERE status='READY'
        ORDER BY 1""")]

    bad = []
    unknown = []                 # 못 닿아서 판정하지 못한 것. **어긋남으로 세지 않는다**
    n_img = n_doc = 0
    for i in ids:
        st, _, body, why = get("/api/v1/item/%d" % i)
        if st is None:
            unknown.append("item %d 상세 - %s" % (i, why))
            continue
        if st != 200:
            bad.append("item %d 상세가 %d" % (i, st))
            continue
        b = _json.loads(body)

        for im in b.get("images") or []:
            n_img += 1
            s2, ct, _b, why2 = get(im["url"])
            if s2 is None:
                unknown.append("%s - %s" % (im["url"], why2))
            elif s2 != 200 or not ct.startswith("image/"):
                bad.append("%s -> %s %s" % (im["url"], s2, ct))
        if b.get("image_count") != len(b.get("images") or []):
            bad.append("item %d image_count 가 목록 길이와 다르다" % i)
        if (b.get("image_count") or 0) > 0 and b.get("images_status") != "READY":
            bad.append("item %d 사진이 있는데 images_status=%s"
                       % (i, b.get("images_status")))

        for d in b.get("documents") or []:
            if not d.get("available"):
                if d.get("viewer_url") is not None:
                    bad.append("item %d %s available=False 인데 URL 을 준다"
                               % (i, d.get("doc_type")))
                continue
            n_doc += 1
            url = d.get("viewer_url")
            if not url:
                bad.append("item %d %s available 인데 URL 이 없다" % (i, d.get("doc_type")))
                continue
            s2, _ct, _b, why2 = get(url)
            if s2 is None:
                unknown.append("%s - %s" % (url, why2))
            elif s2 != 200:
                bad.append("%s -> %s" % (url, s2))

    print("    물건 %d개 / 사진 URL %d개 / 문서 URL %d개 / 열리지 않음 %d개"
          % (len(ids), n_img, n_doc, len(bad)))
    for x in bad[:SAMPLE]:
        print("      %s" % x)
    if unknown:
        # ★ 미확인은 **어긋남에 더하지 않는다.** 대신 숨기지도 않는다 -
        #   "열리지 않음 0" 만 보고 전수 확인됐다고 읽으면 안 되기 때문이다.
        print("    ** 확인하지 못함 %d건 ** (못 닿았다. 결함이라는 뜻이 아니다)"
              % len(unknown))
        for x in unknown[:SAMPLE]:
            print("      %s" % x)
        print("      -> 서버가 살아 있는데도 나면 그 URL 만 다시 요청해 보라."
              " 재요청하면 즉시 200 이 오는 경우가 관측됐다(docs/BUGS.md #194)")
    return len(bad)


def main():
    if not os.path.exists(db_path()):
        print("DB 를 찾을 수 없다: %s" % db_path())
        return 2

    print("=" * 70)
    print(" 자산 무결성 감사 (읽기 전용) - %s" % db_path())
    print("=" * 70)
    print("    ※ 이 숫자는 **이 머신이 여는 DB** 기준이다."
          " 개발 머신과 운영 크롤 머신이 다를 수 있고, 개발 DB 에서 나온 값을"
          " 제품 상태로 읽으면 안 된다 (docs/BUGS.md #200).")

    conn = _connect()
    try:
        problems = 0
        problems += audit_images(conn)
        problems += audit_documents(conn)
        problems += audit_queue_vs_status(conn)
        problems += audit_document_orphans(conn)
        problems += audit_queue_orphans(conn)
        problems += audit_orphan_downloads(conn)
        problems += audit_api_promises(
            conn, os.environ.get("AUDIT_API_BASE", "http://127.0.0.1:8000"))
    finally:
        conn.close()

    print("")
    print("=" * 70)
    if problems:
        print(" 결과: 어긋남 %d건 - 위 목록 참고 (이 스크립트는 고치지 않는다)" % problems)
        return 1
    print(" 결과: 어긋남 없음 - DB 기록과 디스크 실체가 일치한다")
    return 0


if __name__ == "__main__":
    # `--selftest` 는 감사기가 눈이 멀지 않았는지 확인한다(운영 DB 사본만 쓴다).
    sys.exit(selftest() if "--selftest" in sys.argv else main())
