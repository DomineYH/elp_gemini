"""
개별 평가기준 삭제 응답 스키마
"""
from pydantic import BaseModel


class DeleteSingleCriteriaResponse(BaseModel):
    """개별 평가기준 삭제 응답"""
    
    success: bool
    message: str
    criteria_id: int
