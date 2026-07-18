import sys, os
sys.path.insert(0, os.getcwd())
from storage.database import get_connection

conn = get_connection()

print("=== 현재 테이블 목록 ===")
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
for t in tables:
    print(" ", t[0])

print("")
print("=== auction 테이블 스키마 ===")
cols = conn.execute("PRAGMA table_info(auction)").fetchall()
for c in cols:
    print(f"  {c['name']} | {c['type']}")

print("")
print("=== 샘플 데이터 1건 ===")
row = conn.execute("SELECT * FROM auction LIMIT 1").fetchone()
if row:
    for k in row.keys():
        print(f"  {k}: {row[k]}")

conn.close()
