import sqlite3

conn = sqlite3.connect('auction.db')
cur = conn.execute("""
    UPDATE document_queue
    SET last_attempt_at = NULL
    WHERE case_no = '2024타경1775' AND doc_type = 'appraisal'
""")
conn.commit()
print("재시도 잠금 해제된 항목 수:", cur.rowcount)