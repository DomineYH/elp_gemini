-- 마이그레이션: ChatMessage 테이블에 used_criteria_ids 컬럼 추가
-- 목적: QnA 답변에 사용된 평가기준 ID를 추적하기 위한 컬럼 추가
-- 작성일: 2025-01-23

-- used_criteria_ids 컬럼 추가 (JSON 타입, 기본값: 빈 배열)
ALTER TABLE chat_messages ADD COLUMN used_criteria_ids TEXT DEFAULT '[]';

-- 기존 레코드에 빈 배열 설정
UPDATE chat_messages SET used_criteria_ids = '[]' WHERE used_criteria_ids IS NULL;

-- 인덱스 추가 (선택 사항 - 평가기준별 사용 통계 조회 시 성능 향상)
-- CREATE INDEX idx_chat_messages_used_criteria ON chat_messages(used_criteria_ids);
