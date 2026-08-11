-- 010_add_registry_request_reason.sql
-- Admin MVP(등기부 신청 운영): FAILED 처리 시 사유를 저장할 컬럼이 없어 추가한다.
ALTER TABLE registry_requests ADD COLUMN reason TEXT;
