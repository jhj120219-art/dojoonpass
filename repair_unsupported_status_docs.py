"""수집이 **구조적으로 불가능한** 문서를 화면에서 '수집중'으로 두지 않는다.

2026-08-14 신설. `backfill_dong_normalize.py` / `repair_document_status.py`와 같은 관례를
따른다 — 기본은 dry-run, `--apply` 를 줘야 실제로 쓴다.

★★ 2026-08-17 (Sprint 144+) 중요 정정 — 이 스크립트의 원래 대상은 **사라졌다** ★★
-----------------------------------------------------------------------------
아래 "왜 필요한가"는 2026-08-14 시점에는 사실이었지만 **지금은 아니다.**

원래 전제는 "현황조사서는 물건번호가 1일 때의 버튼 id만 확인돼 있다"였고, 그래서
물건번호 2 이상인 629건이 영구 수집 불가였다. 이 파일의 "안전성" 절이 그 상황에 대해
**"나중에 버튼 id가 확보되면 대상이 저절로 줄어든다"**고 후속 조치를 적어 뒀는데,
2026-08-17에 실제로 확보됐다:

    실 브라우저로 물건번호 2인 상세페이지 2건의 DOM을 덤프한 결과
    `mf_wfm_mainFrame_btn_curstExmndcTop`이 **번호 없이 그대로** 존재하고 표시된다.
    오버레이 내용도 사건의 모든 물건을 한 문서에 담고 있다(사건 단위 문서).
    -> `config/settings.py:get_doc_button_id()`가 물건번호와 무관하게 버튼을 돌려준다.

그 결과 이 스크립트가 실제로 잡는 행은 **0건**이 됐다(2026-08-17 dry-run 실측).
규칙을 여기 베끼지 않고 **코드에 물어보도록** 설계한 덕분에 스크립트 자체는 고칠 것이
없었다 — 대상이 저절로 비었다. 설계가 의도대로 동작한 사례다.

★ `--apply`는 **한 번도 실행된 적이 없다**(실측: document_status의 STATUS FAILED가 1행뿐이고
  그 1행은 이 스크립트가 아니라 수집 실패로 생긴 것). 따라서 되돌릴 행도 없다.

이 파일을 지우지 않고 남기는 이유: 앞으로 다른 doc_type이 같은 상황(버튼 id 미확보)에
빠지면 그대로 재사용할 수 있고, 판정을 코드에 위임하므로 대상이 생기는 순간 자동으로
잡는다. 아래 서술은 **2026-08-14 당시의 기록**으로 읽어야 한다.

왜 필요했는가 (2026-08-14 당시 실측 — 지금은 해소됨)
-----------------------------------------------------------------------------
현황조사서(STATUS)는 **물건번호가 1일 때의 수집 버튼 id만 확인돼 있었다.**

    config/settings.py:get_doc_button_id("status", "1")   -> 버튼 id 있음
    config/settings.py:get_doc_button_id("status", "2")   -> None  (미지원)   <- 지금은 버튼 id를 준다

즉 물건번호가 2 이상인 물건의 현황조사서는 **수집 자체가 불가능**했다. 추측으로
셀렉터를 만들지 않는다는 것이 이 저장소의 방침이라(잘못된 id로 엉뚱한 버튼을 누르는
것을 막는다), 이것은 버그가 아니라 **알려진 수집 한계**였다.

문제는 그 한계가 화면에 어떻게 보이는가였다. 2026-08-14 실측:

    물건번호 != 1 인 STATUS 행        629
      document_status = COLLECTING    628   <- 화면에 "수집중"
      document_status = FAILED          1

**628건이 영원히 도착하지 않을 문서를 "수집중"이라고 말하고 있었다.**
`docs/BUGS.md` #69가 지적한 "도착하지 않을 문서를 기다리는 상태"와 같은 모양이고,
이쪽은 기다림이 끝날 수 없다는 것이 **코드로 확정**돼 있다는 점이 달랐다.
(2026-08-17 정정: 이제는 끝날 수 있다 — 그 628건은 정상적인 수집 대기 상태다.)

새 정책을 만드는 것이 아니다
-----------------------------------------------------------------------------
"이 경우 FAILED로 둔다"는 **이미 정해져 있다.** Sprint 75가 같은 자리에서 판단했고
(`test_document_queue.py` §14), Sprint 101의 `mark_queue_unsupported()`가 그대로 구현한다.

    큐에서 빼면 document_status가 COLLECTING("수집중")에 영원히 머문다 - BUGS #69와
    똑같은 상태가 된다. 지금처럼 빠르게 실패해 FAILED로 남기는 쪽이 더 정직하다.

앞으로 doc_worker가 집는 행은 그 규칙을 탄다. 그런데 **이미 쌓인 628행은 doc_worker가
집지 않는다** — 대부분 매각기일이 지나 2차 방어선(SKIPPED_EXPIRED)에 먼저 걸리기
때문이다. 그래서 그 행들만 같은 규칙으로 맞춘다.

안전성
-----------------------------------------------------------------------------
* 대상은 **`get_doc_button_id()`가 실제로 None을 주는 행**뿐이다. 규칙을 여기 베끼지
  않고 **코드에 물어본다** — 나중에 버튼 id가 확보되면 대상이 저절로 줄어든다.
* `READY`인 행은 **절대 건드리지 않는다.** 파일이 실제로 있는 문서를 "수집실패"로
  가리면 사용자가 볼 수 있는 것을 못 보게 된다(정반대 방향의 결함).
* `document_status`만 바꾼다. 큐(`document_queue`)는 건드리지 않는다 — 큐의 종결은
  doc_worker가 자기 규칙으로 한다.
* 되돌릴 수 있다: 버튼 id가 확보되면 이 행들을 다시 COLLECTING으로 돌리고 큐에 넣으면 된다.

    python repair_unsupported_status_docs.py            # dry-run (기본)
    python repair_unsupported_status_docs.py --apply    # 실제 반영
"""
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import get_doc_button_id
from storage.database import QUEUE_TO_DOC_STATUS_TYPE

DB_PATH = "auction.db"

# document_status.doc_type(대문자) -> 큐 doc_type(소문자). 규칙을 베끼지 않고 뒤집어 쓴다.
DS_TO_QUEUE = {v: k for k, v in QUEUE_TO_DOC_STATUS_TYPE.items()}


def plan(conn):
    """바꿀 행을 계산한다(쓰지 않는다)."""
    rows = conn.execute("""
        SELECT d.id AS ds_id, d.doc_type, d.status,
               ai.id AS item_id, ai.case_no, ai.item_no, ai.court_name, ai.auction_date
        FROM document_status d
        JOIN auction_item ai ON ai.id = d.item_id
    """).fetchall()

    targets, skipped_ready, unsupported_total = [], 0, 0
    for r in rows:
        queue_type = DS_TO_QUEUE.get((r["doc_type"] or "").upper())
        if not queue_type:
            continue
        # ★ 판정은 코드에 물어본다(규칙 복제 금지).
        if get_doc_button_id(queue_type, r["item_no"]) is not None:
            continue
        unsupported_total += 1
        if r["status"] == "READY":
            # 실제로 파일이 있는 경우다. 절대 덮지 않는다.
            skipped_ready += 1
            continue
        if r["status"] == "FAILED":
            continue  # 이미 맞다
        targets.append(r)
    return targets, skipped_ready, unsupported_total


def main() -> int:
    apply = "--apply" in sys.argv
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        targets, skipped_ready, unsupported_total = plan(conn)

        print("수집 버튼 id가 없는 document_status 행 : %d" % unsupported_total)
        print("  이미 FAILED (그대로 둠)             : %d"
              % (unsupported_total - len(targets) - skipped_ready))
        print("  READY (파일 있음 - 건드리지 않음)    : %d" % skipped_ready)
        print("  COLLECTING -> FAILED 대상           : %d" % len(targets))

        live = [t for t in targets
                if (t["auction_date"] or "") >= datetime.now().strftime("%Y-%m-%d")]
        print("  그중 매각기일이 남은 행              : %d" % len(live))
        for t in targets[:8]:
            print("      item=%-6s %-16s 물건%-3s %s 기일=%s"
                  % (t["item_id"], (t["case_no"] or "")[:16], t["item_no"],
                     t["doc_type"], t["auction_date"]))
        if len(targets) > 8:
            print("      ... 외 %d건" % (len(targets) - 8))

        if not apply:
            print("\n[DRY-RUN] 아무것도 쓰지 않았다. 반영하려면 --apply 를 붙여라.")
            return 0

        now = datetime.now().isoformat()
        for t in targets:
            conn.execute("UPDATE document_status SET status='FAILED', updated_at=? WHERE id=?",
                         (now, t["ds_id"]))
        conn.commit()
        print("\n[APPLIED] %d행 반영" % len(targets))

        left, _, _ = plan(conn)
        print("남은 COLLECTING 대상: %d행" % len(left))
        return 0 if not left else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
