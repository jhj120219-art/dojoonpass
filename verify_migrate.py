import sys, os, time, subprocess
sys.path.insert(0, os.getcwd())
from storage.database import get_connection

conn = get_connection()
before_a = conn.execute("SELECT COUNT(*) FROM auction").fetchone()[0]
before_ac = conn.execute("SELECT COUNT(*) FROM auction_case").fetchone()[0]
before_ai = conn.execute("SELECT COUNT(*) FROM auction_item").fetchone()[0]
conn.close()

print(f"실행 전 auction: {before_a}건")
print(f"실행 전 auction_case: {before_ac}건")
print(f"실행 전 auction_item: {before_ai}건")
print("migrate_execute.py 실행 중...")

start = time.time()
result = subprocess.run(
    ["C:\\ProgramData\\Anaconda3\\python.exe", "migrate_execute.py"],
    capture_output=True, text=True, encoding="utf-8", errors="ignore"
)
elapsed = round(time.time() - start, 2)

conn2 = get_connection()
after_ac = conn2.execute("SELECT COUNT(*) FROM auction_case").fetchone()[0]
after_ai = conn2.execute("SELECT COUNT(*) FROM auction_item").fetchone()[0]
conn2.close()

print(f"실행 시간: {elapsed}초")
print(f"exit code: {result.returncode}")
print(f"auction_case: {before_ac} -> {after_ac} (증가: {after_ac - before_ac}건)")
print(f"auction_item: {before_ai} -> {after_ai} (증가: {after_ai - before_ai}건)")
if result.returncode == 0:
    print("exit code 0 확인 완료")
else:
    print("오류:", result.stderr[:200])
