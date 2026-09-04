# -*- coding: utf-8 -*-
"""Time-to-Decision(T2D) 측정 — **읽기 전용. 아무것도 바꾸지 않는다.**

## T2D 가 무엇인가

콕찰이 줄이겠다고 말하는 것은 "경매 의사결정에 드는 시간"이다. 그 시간의 이름이 T2D 다:

    물건을 **처음** 발견한 시점  ->  입찰 여부를 **판단**한 시점

이 스크립트는 그 시간을 **지금 있는 데이터로 잴 수 있는 만큼만** 재고,
잴 수 없는 부분은 **잴 수 없다고 말한다.** 숫자를 지어내지 않는다.

## 왜 새 이벤트 테이블을 만들지 않았나

필요한 시각이 이미 대부분 있다. 새 표를 만들면 같은 사실이 두 곳에 생기고,
그 둘이 갈라지는 날이 온다(이 저장소가 반복해 겪은 모양).

    DISCOVER  recent_items.first_viewed_at   처음 본 시각   (migration 031)
    FIELD     field_visits.started_at         임장 시작      (migration 030)
              field_visits.completed_at       임장 완료
    DECIDE    field_visits.decided_at         판단한 시각

## 지금 잴 수 있는 것과 없는 것 (정직하게)

    잰다      FIELD_START -> DECIDE   두 값 모두 030 이 만든다
    잰다      DISCOVER -> DECIDE      031 이 적용되고 그 뒤 조회가 쌓인 사용자만
    못 잰다   031 이전에 본 물건      `first_viewed_at` 이 NULL 이다(모름)
    못 잰다   `recent_items` 에서 잘린 물건
              `RECENT_ITEMS_DISPLAY_LIMIT`(20) 밖의 행은 삭제된다. 물건을 많이 보는
              사용자일수록 **처음 본 기록이 먼저 사라진다** — 즉 T2D 는 지금 구조에서
              가벼운 사용자 쪽으로 치우쳐 측정된다. 보존 정책 변경은 제품 결정이라
              이 스크립트가 정하지 않고, 측정할 때마다 이 한계를 함께 보고한다.

    python audit_time_to_decision.py
"""
import io
import os
import sys
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _force_utf8_stdout():
    """콘솔 인코딩 고정. **`__main__` 에서만 부른다**(BUGS #192 계열, 2026-09-04)."""
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")


import storage.database as _db          # noqa: E402


def _ro(path):
    return sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)


def _has_table(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _has_column(conn, table, column):
    return conn.execute(
        "SELECT 1 FROM pragma_table_info(?) WHERE name=?", (table, column)
    ).fetchone() is not None


def _hours(a, b):
    """b - a 를 시간 단위로. 못 읽으면 None."""
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return None


def _summarize(values):
    """중앙값 중심으로 본다 — 평균은 한 건의 긴 고민에 통째로 끌려간다."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    mid = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    return {"n": n, "median_h": mid, "min_h": vals[0], "max_h": vals[-1]}


def _line(label, s):
    if s is None:
        print("    %-28s 표본 없음" % label)
    else:
        print("    %-28s 표본 %d건 · 중앙값 %.1f시간 (최소 %.1f / 최대 %.1f)"
              % (label, s["n"], s["median_h"], s["min_h"], s["max_h"]))


def main():
    path = _db.DB_PATH
    print("=" * 66)
    print(" Time-to-Decision 측정 (읽기 전용)")
    print("=" * 66)
    if not os.path.exists(path):
        print("  DB 가 없다: %s" % path)
        print("  -> 측정하지 못했다. **통과가 아니다.**")
        return 1
    print("  DB: %s" % path)

    conn = _ro(path)
    try:
        # ── 무엇을 잴 수 있는 환경인가 ────────────────────────────────────
        has_visits = _has_table(conn, "field_visits")
        has_first = (_has_table(conn, "recent_items")
                     and _has_column(conn, "recent_items", "first_viewed_at"))
        print("\n[0] 측정 가능 여부")
        print("    field_visits (030)            : %s" % ("있음" if has_visits else "없음"))
        print("    recent_items.first_viewed_at (031): %s" % ("있음" if has_first else "없음"))
        if not has_visits:
            print("\n  -> 임장/판단 기록이 없어 T2D 를 **한 구간도 잴 수 없다.**")
            print("     migration 030 적용이 필요하다(승인 영역).")
            return 0

        # ── 판단이 얼마나 쌓였나 ──────────────────────────────────────────
        total = conn.execute("SELECT COUNT(*) FROM field_visits").fetchone()[0]
        decided = conn.execute(
            "SELECT COUNT(*) FROM field_visits WHERE decided_at IS NOT NULL").fetchone()[0]
        done = conn.execute(
            "SELECT COUNT(*) FROM field_visits WHERE completed_at IS NOT NULL").fetchone()[0]
        print("\n[1] 기록 규모")
        print("    임장 기록          %d건" % total)
        print("    임장 완료          %d건" % done)
        print("    판단까지 남긴 것    %d건" % decided)
        if decided == 0:
            print("\n  -> 판단 기록이 아직 없다. **숫자를 만들지 않는다.**")
            print("     T2D 는 판단이 쌓인 뒤에 의미가 생긴다.")
            return 0

        # ── 구간별 소요 시간 ──────────────────────────────────────────────
        rows = conn.execute(
            "SELECT user_id, item_id, started_at, completed_at, decided_at"
            "  FROM field_visits WHERE decided_at IS NOT NULL").fetchall()
        field_to_decide = [_hours(r[2], r[4]) for r in rows]
        visit_span = [_hours(r[2], r[3]) for r in rows if r[3]]
        print("\n[2] 잴 수 있는 구간")
        _line("임장 시작 -> 판단", _summarize(field_to_decide))
        _line("임장 시작 -> 임장 완료", _summarize(visit_span))

        # ── 전체 T2D (처음 발견 -> 판단) ──────────────────────────────────
        print("\n[3] 전체 T2D (처음 발견 -> 판단)")
        if not has_first:
            print("    ** 잴 수 없다 ** - `recent_items.first_viewed_at` 이 없다"
                  " (migration 031 미적용).")
            print("    그전까지 `viewed_at` 으로 대신 재지 않는다 - 그 값은 재조회마다")
            print("    덮어써져서, 오래 고민한 물건일수록 T2D 가 **짧게** 나온다.")
        else:
            full = conn.execute("""
                SELECT ri.first_viewed_at, fv.decided_at
                  FROM field_visits fv
                  JOIN recent_items ri
                    ON ri.user_id = fv.user_id AND ri.item_id = fv.item_id
                 WHERE fv.decided_at IS NOT NULL
                   AND ri.first_viewed_at IS NOT NULL
            """).fetchall()
            _line("처음 발견 -> 판단", _summarize([_hours(a, b) for a, b in full]))
            missing = decided - len(full)
            if missing > 0:
                print("    (판단 %d건 중 %d건은 처음 본 시각을 모른다 -"
                      " 031 이전 조회이거나 목록에서 잘렸다)" % (decided, missing))

        # ── 판단 분포 ─────────────────────────────────────────────────────
        print("\n[4] 판단 분포 (사용자가 고른 값. 제품이 계산하지 않는다)")
        for value, n in conn.execute(
                "SELECT decision, COUNT(*) FROM field_visits"
                " WHERE decision IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"):
            print("    %-6s %d건" % (value, n))

        # ── 측정의 한계를 **매번** 함께 말한다 ────────────────────────────
        print("\n[5] 이 숫자가 참인 범위")
        print("    · `recent_items` 는 사용자당 %d건까지만 남는다"
              % _recent_limit())
        print("      -> 물건을 많이 보는 사용자일수록 처음 본 기록이 먼저 사라진다.")
        print("         지금 T2D 는 **가벼운 사용자 쪽으로 치우쳐** 측정된다.")
        print("    · 임장을 하지 않고 판단한 물건은 여기 잡히지 않는다"
              " (판단 기록이 임장에 붙어 있다).")
        print("    · 표본이 적을 때 중앙값은 흔들린다. 몇 % 단축 같은 주장은"
              " 표본이 쌓인 뒤에 한다.")
        return 0
    finally:
        conn.close()


def _recent_limit():
    """정본에서 읽는다 — 숫자를 여기 다시 적지 않는다."""
    try:
        from api.v1.recent_items import RECENT_ITEMS_DISPLAY_LIMIT
        return RECENT_ITEMS_DISPLAY_LIMIT
    except Exception:                       # noqa: BLE001
        return -1


if __name__ == "__main__":
    _force_utf8_stdout()
    sys.exit(main())
