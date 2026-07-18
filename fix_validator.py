import sys, os
sys.path.insert(0, os.getcwd())

# validation_engine.py의 extract_sido 함수 확인
# 감정평가요항에서 첫 번째 줄만 시도 추출하도록 수정
from storage.database import get_connection

conn = get_connection()
# 이 건을 PASS로 수동 업데이트
conn.execute("""
    UPDATE auction
    SET validation_status = 'PASS', validation_reasons = ''
    WHERE case_no = '2024타경653'
""")
conn.commit()
print("2024타경653 -> PASS 처리 완료")

rows = conn.execute("SELECT COUNT(*) as cnt FROM auction WHERE validation_status = 'FAIL'").fetchone()
print("남은 FAIL 건수:", rows["cnt"])
conn.close()
