import sys, os
sys.path.insert(0, os.getcwd())
from storage.database import get_connection

conn = get_connection()

print("=== auction 테이블 스키마 ===")
cols = conn.execute("PRAGMA table_info(auction)").fetchall()
for c in cols:
    print(f"  cid={c[0]} | name={c[1]} | type={c[2]} | notnull={c[3]} | default={c[4]}")

print("")
print("=== auction 샘플 3건 ===")
rows = conn.execute("SELECT * FROM auction LIMIT 3").fetchall()
for row in rows:
    for k in row.keys():
        print(f"  {k}: {row[k]}")
    print()

print("=== auction 전체 건수 ===")
cnt = conn.execute("SELECT COUNT(*) FROM auction").fetchone()[0]
print(f"  총 {cnt}건")

print("")
print("=== 중복 사건번호 확인 ===")
dupes = conn.execute("""
    SELECT case_no, COUNT(*) as cnt
    FROM auction
    GROUP BY case_no
    HAVING cnt > 1
    LIMIT 5
""").fetchall()
print(f"  중복 사건번호 수: {len(dupes)}건")
for d in dupes:
    print(f"  {d['case_no']}: {d['cnt']}건")

conn.close()
