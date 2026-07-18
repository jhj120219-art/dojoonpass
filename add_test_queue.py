from storage.database import init_db, enqueue_documents

init_db()
enqueue_documents([{
    'court_code': '서울중앙지방법원',
    'case_no': '2024타경1775',
    'auction_date': '2026-07-15'
}])
print("큐에 넣기 완료")