"""관리자 스키마"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class AdminDashboardResponse(BaseModel):
    """관리자 대시보드 응답 모델"""

    total_users: int = Field(..., description="전체 사용자 수")
    total_documents: int = Field(..., description="전체 문서 수")
    documents_last_7days: int = Field(
        ..., description="최근 7일 문서 업로드 수"
    )
    total_qna_logs: int = Field(..., description="전체 QnA 요청 수")
    qna_logs_last_7days: int = Field(
        ..., description="최근 7일 QnA 요청 수"
    )
    total_evaluation_runs: int = Field(..., description="전체 평가 실행 수")
    evaluation_runs_last_7days: int = Field(
        ..., description="최근 7일 평가 실행 수"
    )
    active_prompts: int = Field(..., description="활성 시스템 프롬프트 수")


class AdminUserResponse(BaseModel):
    """관리자 사용자 목록 응답 모델"""

    id: int
    email: str
    is_admin: bool
    created_at: datetime
    document_count: int = Field(
        ..., description="사용자가 업로드한 문서 수"
    )
    qna_count: int = Field(..., description="사용자의 QnA 요청 수")

    model_config = {"from_attributes": True}


class AdminUserDetailResponse(BaseModel):
    """관리자 사용자 상세 응답 모델"""

    id: int
    email: str
    is_admin: bool
    created_at: datetime
    documents: list = Field(..., description="사용자 문서 목록")
    recent_qna_logs: list = Field(
        ..., description="최근 QnA 로그 (최대 10개)"
    )
    evaluation_runs: list = Field(
        ..., description="평가 실행 목록"
    )

    model_config = {"from_attributes": True}


class AdminQALogResponse(BaseModel):
    """관리자 QnA 로그 응답 모델 (레거시)"""

    id: int
    document_id: int
    document_title: str = Field(..., description="문서 제목")
    user_id: int
    user_email: str = Field(..., description="사용자 이메일")
    prompt_id: int
    prompt_version: int = Field(..., description="프롬프트 버전")
    question: str
    answer: str
    latency_ms: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


# ===== 새로운 세션 기반 QnA 로그 스키마 =====


class QnAMessageItem(BaseModel):
    """개별 메시지 아이템"""

    id: int
    role: str = Field(..., description="발화 주체 (user 또는 assistant)")
    content: str = Field(..., description="메시지 내용")
    created_at: datetime

    model_config = {"from_attributes": True}


class QnASessionLogResponse(BaseModel):
    """세션 단위 QnA 로그 응답"""

    session_id: int
    user_type: Optional[str] = Field(
        None, description="사용자 유형 (1학년, 2학년, 3학년, 4학년, 교사)"
    )
    title: Optional[str] = Field(None, description="세션 제목 (지도안 파일명)")
    messages: List[QnAMessageItem] = Field(
        default_factory=list, description="대화 메시지 목록"
    )
    message_count: int = Field(..., description="메시지 수")
    created_at: datetime

    model_config = {"from_attributes": True}


class QnALogsPageResponse(BaseModel):
    """페이징된 QnA 로그 응답"""

    sessions: List[QnASessionLogResponse] = Field(
        default_factory=list, description="세션 목록"
    )
    total: int = Field(..., description="전체 세션 수")
    page: int = Field(..., description="현재 페이지")
    page_size: int = Field(..., description="페이지 크기")
