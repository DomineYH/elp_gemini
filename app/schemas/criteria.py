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
        description=(
            "표시명. ASCII printable(U+0020–U+007E) 및 한글(Hangul) 문자만 "
            "허용. None/빈 문자열이면 alias 제거."
        ),
    )

    @field_validator("display_alias")
    def validate_alias(cls, v):
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        if not all(_is_allowed_alias_char(c) for c in v):
            raise ValueError(
                "표시명에 허용되지 않는 문자가 포함되어 있습니다. "
                "ASCII 또는 한글만 입력하세요."
            )
        if len(v) > 255:
            raise ValueError("표시명은 255자 이내로 입력하세요.")
        return v


def _is_allowed_alias_char(ch: str) -> bool:
    """display_alias에 허용되는 문자인지 판별.

    허용: ASCII printable + Hangul Syllables/Jamo/Compatibility Jamo.
    거부: 제어 문자, 이모지, 그 외 모든 스크립트.
    """
    code = ord(ch)
    if 0x20 <= code < 0x7F:
        return True
    if 0xAC00 <= code <= 0xD7A3:
        return True
    if 0x1100 <= code <= 0x11FF:
        return True
    if 0x3130 <= code <= 0x318F:
        return True
    return False


class UpdateDisplayAliasResponse(BaseModel):
    """평가기준 표시명 업데이트 응답"""

    success: bool = Field(description="성공 여부")
    criteria_id: int = Field(description="평가기준 ID")
    display_alias: Optional[str] = Field(description="업데이트 후 alias (None 가능)")
