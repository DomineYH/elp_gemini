-- ===============================================================
-- criteria 테이블 file_path 컬럼 추가
-- 생성일: 2025-11-22
-- 목적: 파일 경로 메타데이터 저장 컬럼 누락 시 복구
-- ===============================================================

ALTER TABLE criteria
  ADD COLUMN file_path TEXT NOT NULL DEFAULT 'legacy_missing';

UPDATE criteria
  SET file_path = 'legacy_missing'
  WHERE file_path IS NULL OR TRIM(file_path) = '';

-- ===============================================================
-- Migration Complete
-- ===============================================================





