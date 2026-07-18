import sys, os
sys.path.insert(0, os.getcwd())
from storage.database import get_connection
from datetime import datetime

conn = get_connection()
now = datetime.now().isoformat()
conn.execute("DELETE FROM document_collect_failures")
conn.execute("UPDATE document_status SET status = 'COLLECTING', updated_at = ? WHERE status = 'FAILED'", (now,))
conn.commit()
cnt = conn.execute("SELECT COUNT(*) FROM document_collect_failures").fetchone()[0]
fail_cnt = conn.execute("SELECT COUNT(*) FROM document_status WHERE status = 'FAILED'").fetchone()[0]
print("실패 로그:", cnt, "건")
print("FAILED status:", fail_cnt, "건")
conn.close()
