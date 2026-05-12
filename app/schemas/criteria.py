"""
평가기준 스키마
Vector DB 기반 평가기준 관리
"""
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


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

    display_alias: Optional[str] = Field(
        default=None,
        description="ASCII-only 표시명. None/빈 문자열이면 alias 제거"
    )

    @field_validator("display_alias")
    def validate_alias(cls, v):
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        if not all(0x20 <= ord(c) < 0x7F for c in v):
            raise ValueError("표시 가능한 ASCII 문자만 허용됩니다.")
        if len(v) > 255:
            raise ValueError("표시명은 255자 이내로 입력하세요.")
        return v


class UpdateDisplayAliasResponse(BaseModel):
    """평가기준 표시명 업데이트 응답"""

    success: bool = Field(description="성공 여부")
    criteria_id: int = Field(description="평가기준 ID")
    display_alias: Optional[str] = Field(description="업데이트 후 alias (None 가능)")
