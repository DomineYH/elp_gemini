"""
채팅 세션 및 메시지 스키마
세션 기반 QnA 관리
"""
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    """세션 생성 요청"""

    lessonplan_filename: str = Field(
        ...,
        min_length=1,
        description="지도안 파일명"
    )


class CreateSessionResponse(BaseModel):
    """세션 생성 응답"""

    session_id: int = Field(
        ..., description="생성된 세션 ID"
    )
    user_id: int = Field(
        ..., description="사용자 ID"
    )
    lessonplan_filename: str = Field(
        ..., description="지도안 파일명"
    )
    created_at: datetime = Field(
        ..., description="생성 시간"
    )


class AskQuestionRequest(BaseModel):
    """질문 요청"""

    question: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="질문 내용"
    )


class AskQuestionResponse(BaseModel):
    """질문 응답"""

    session_id: int = Field(
        ..., description="세션 ID"
    )
    question: str = Field(
        ..., description="질문"
    )
    answer: str = Field(
        ..., description="답변"
    )
    latency_ms: Optional[int] = Field(
        None, description="응답 시간 (ms)"
    )
    citations: Optional[Any] = Field(
        None, description="인용 정보"
    )


class ChatMessageResponse(BaseModel):
    """채팅 메시지 응답"""

    id: int
    session_id: int
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatHistoryResponse(BaseModel):
    """채팅 히스토리 응답"""

    session_id: int = Field(
        ..., description="세션 ID"
    )
    messages: List[ChatMessageResponse] = Field(
        default_factory=list,
        description="메시지 목록"
    )
    total_count: int = Field(
        ..., description="전체 메시지 수"
    )
