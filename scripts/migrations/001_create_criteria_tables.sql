-- =================================================================
-- Admin Evaluation Criteria System - DB Schema Migration
-- 생성일: 2025-11-20
-- 목적: 평가 기준 문서 관리를 위한 테이블 생성
-- =================================================================

-- -----------------------------------------------------------------
-- 1. 평가 기준 문서 메타데이터 테이블
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS criteria_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  file_path TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  file_size INTEGER NOT NULL,
  vector_store_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'uploaded',
  -- 상태: uploaded | active | archived | error
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  activated_at TIMESTAMP,
  activated_by INTEGER
);

-- 인덱스: 상태 및 생성일 기준 조회 최적화
CREATE INDEX IF NOT EXISTS idx_criteria_status
  ON criteria_documents(status);
CREATE INDEX IF NOT EXISTS idx_criteria_created
  ON criteria_documents(created_at DESC);

-- -----------------------------------------------------------------
-- 2. 단일 활성 기준 문서 관리 테이블
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS active_criteria (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  -- id=1로 고정하여 단일 row만 허용
  criteria_document_id INTEGER UNIQUE,
  activated_at TIMESTAMP,
  activated_by INTEGER,
  FOREIGN KEY(criteria_document_id)
    REFERENCES criteria_documents(id)
);

-- -----------------------------------------------------------------
-- 3. 감사 로그 테이블
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS criteria_audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT NOT NULL,
  -- 액션: upload | activate | deactivate | search
  criteria_document_id INTEGER,
  actor_id INTEGER,
  detail TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(criteria_document_id)
    REFERENCES criteria_documents(id)
);

-- 인덱스: 액션 및 생성일 기준 조회 최적화
CREATE INDEX IF NOT EXISTS idx_audit_action
  ON criteria_audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_created
  ON criteria_audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_criteria
  ON criteria_audit_logs(criteria_document_id);

-- =================================================================
-- Migration Complete
-- =================================================================
