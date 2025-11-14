"""문서 스키마"""
from datetime import datetime
from pydantic import BaseModel, Field


class DocumentResponse(BaseModel):
    """문서 응답 모델"""

    id: int
    user_id: int
    title: str
    file_size: int
    status: str
    uploaded_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentDetailResponse(DocumentResponse):
    """문서 상세 응답 모델"""

    random_key: str
    file_path: str
    file_search_file_id: str | None
    store_id: str | None


class DocumentUpload(BaseModel):
    """문서 업로드 요청 모델"""

    title: str = Field(..., min_length=1, max_length=255)
