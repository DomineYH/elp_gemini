"""
수업 지도안 분석 라우터
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.services.lessonplan_analysis_service import LessonPlanAnalysisService
from app.schemas.lessonplan_analysis import (
    LessonPlanAnalysisRequest,
    LessonPlanAnalysisResponse
)
from app.models.users import User

router = APIRouter(prefix="/api/lessonplan", tags=["lessonplan"])


@router.post("/analyze", response_model=LessonPlanAnalysisResponse)
async def analyze_lesson_plan(
    request: LessonPlanAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    수업 지도안 체계적 평가

    평가기준 문서를 근거로 사용자의 수업 지도안을 5개 항목으로 평가하고
    Markdown 형식의 분석 보고서를 생성합니다.

    **평가 항목:**
    1. 교육과정 목표 및 성격과의 부합
    2. 내용 체계 및 성취기준 달성
    3. 교수·학습 방법의 적절성
    4. 평가 방향과의 일치
    5. 개선 및 보완을 위한 제안

    **처리 시간:** 약 30-180초
    """
    try:
        service = LessonPlanAnalysisService(db=db)
        result = await service.analyze_lesson_plan(
            session_id=request.session_id,
            username=current_user.username
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "분석 중 오류 발생")
            )

        return LessonPlanAnalysisResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 오류: {str(e)}"
        )
