"""
수업 지도안 분석 라우터
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.analysis_reports import AnalysisReport
from app.models.users import User
from app.schemas.analysis_reports import (
    AnalysisReportItem,
    AnalysisReportListResponse,
)
from app.schemas.lessonplan_analysis import (
    LessonPlanAnalysisRequest,
    LessonPlanAnalysisResponse,
)
from app.services.lessonplan_analysis_service import LessonPlanAnalysisService

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
            user_id=current_user.id,
        )

        if not result.get("success"):
            if result.get("error_code") == "ALREADY_ANALYZED":
                report_id = result.get("report_id")
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={
                        "detail": result.get(
                            "error", "이미 분석된 문서입니다."
                        ),
                        "report_id": report_id,
                    },
                    headers={"X-Report-Id": str(report_id)},
                )
            if result.get("error_code") == "RESOURCE_EXHAUSTED":
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=result.get("error", "잠시 후 다시 시도해주세요."),
                    headers={"Retry-After": "30"},
                )
            if result.get("error_code") == "MODEL_OVERLOADED":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=result.get(
                        "error",
                        "AI 모델이 일시적으로 혼잡합니다. "
                        "잠시 후 다시 시도해주세요.",
                    ),
                    headers={"Retry-After": "30"},
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "분석 중 오류 발생"),
            )

        return LessonPlanAnalysisResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 오류: {str(e)}"
        )


@router.get("/reports", response_model=AnalysisReportListResponse)
async def list_analysis_reports(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    분석 보고서 목록 조회

    사용자의 모든 분석 보고서 목록을 조회합니다.
    보고서는 생성일 기준 내림차순으로 정렬됩니다.
    """
    try:
        result = await db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.user_id == current_user.id)
            .order_by(AnalysisReport.created_at.desc())
        )
        reports = result.scalars().all()

        return AnalysisReportListResponse(
            username=current_user.username,
            reports=[
                AnalysisReportItem.model_validate(report)
                for report in reports
            ],
            total_count=len(reports)
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"보고서 목록 조회 실패: {str(e)}"
        )


@router.get("/reports/{report_id}")
async def get_analysis_report(
    report_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    분석 보고서 상세 조회

    특정 분석 보고서의 내용을 조회합니다.
    """
    try:
        result = await db.execute(
            select(AnalysisReport)
            .where(
                AnalysisReport.id == report_id,
                AnalysisReport.user_id == current_user.id
            )
        )
        report = result.scalar_one_or_none()

        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="보고서를 찾을 수 없습니다."
            )

        # 보고서 파일 내용 읽기
        report_path = Path(report.report_path)
        if not report_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="보고서 파일이 존재하지 않습니다."
            )

        content = report_path.read_text(encoding="utf-8")

        return {
            "id": report.id,
            "lessonplan_filename": report.lessonplan_filename,
            "lessonplan_original_name": report.lessonplan_original_name,
            "report_filename": report.report_filename,
            "content": content,
            "latency_ms": report.latency_ms,
            "created_at": report.created_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"보고서 조회 실패: {str(e)}"
        )


@router.get("/reports/{report_id}/download")
async def download_analysis_report(
    report_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    분석 보고서 다운로드

    분석 보고서 파일을 다운로드합니다.
    """
    try:
        result = await db.execute(
            select(AnalysisReport)
            .where(
                AnalysisReport.id == report_id,
                AnalysisReport.user_id == current_user.id
            )
        )
        report = result.scalar_one_or_none()

        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="보고서를 찾을 수 없습니다."
            )

        report_path = Path(report.report_path)
        if not report_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="보고서 파일이 존재하지 않습니다."
            )

        return FileResponse(
            path=str(report_path),
            filename=report.report_filename,
            media_type="text/markdown"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"보고서 다운로드 실패: {str(e)}"
        )
