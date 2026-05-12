"""
평가기준 스키마
Vector DB 기반 평가기준 관리
"""
from typing import Optional, List
from pydantic import BaseModel, Field, validator


class UploadCriteriaResponse(BaseModel):
    """평가기준 업로드 응답"""

    file_id: str = Field(
        ..., description="Gemini File ID"
    )
    display_name: str = Field(
        ..., description="파일 표시 이름"
    )
    file_size: int = Field(
        ..., description="파일 크기 (bytes)"
    )
    upload_status: str = Field(
        ..., description="업로드 상태"
    )


class DeleteCriteriaResponse(BaseModel):
    """평가기준 삭제 응답"""

    success: bool = Field(
        ..., description="삭제 성공 여부"
    )
    message: str = Field(
        ..., description="결과 메시지"
    )
    deleted_count: int = Field(
        default=0,
        description="삭제된 문서 수"
    )


class DeleteSingleCriteriaResponse(BaseModel):
    """개별 평가기준 삭제 응답"""
    
    success: bool = Field(
        ..., description="삭제 성공 여부"
    )
    message: str = Field(
        ..., description="결과 메시지"
    )
    criteria_id: int = Field(
        ..., description="삭제된 평가기준 ID"
    )


class UpdateDisplayAliasRequest(BaseModel):
    """평가기준 표시명(alias) 업데이트 요청"""

    display_alias: Optional[str] = None

    @validator("display_alias")
    def validate_alias(cls, v):
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        if not v.isascii():
            raise ValueError("ASCII 문자만 허용됩니다.")
        if len(v) > 255:
            raise ValueError("표시명은 255자 이내로 입력하세요.")
        return v


class UpdateDisplayAliasResponse(BaseModel):
    """평가기준 표시명 업데이트 응답"""

    success: bool
    criteria_id: int
    display_alias: Optional[str]
