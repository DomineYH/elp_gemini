"""
평가 라우터
지도안 평가 실행 및 결과 조회 엔드포인트
"""
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
import logging

from app.dependencies import get_current_user
from app.models.users import User
from app.schemas.evaluations import (
    RunEvaluationRequest,
    RunEvaluationResponse,
    GetEvaluationResponse,
)
from app.services.eval_service import EvaluationService
from app.services.analysis_storage_service import (
    AnalysisStorageService
)

router = APIRouter(
    prefix="/api/evaluations",
    tags=["평가"]
)
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=RunEvaluationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="평가 실행",
    description="지도안 평가를 실행하고 결과를 저장합니다.",
)
async def run_evaluation(
    request: RunEvaluationRequest,
    current_user: User = Depends(get_current_user),
):
    """
    평가 실행

    Args:
        request: 평가 실행 요청
        current_user: 현재 로그인한 사용자

    Returns:
        평가 결과 정보

    Raises:
        HTTPException: 평가 실행 실패
    """
    try:
        eval_service = EvaluationService()

        # 평가 실행
        result = await eval_service.run_evaluation(
            user_id=current_user.id,
            lessonplan_filename=request.lessonplan_filename,
            evaluation_type=request.evaluation_type,
        )

        logger.info(
            f"평가 실행 완료: "
            f"user_id={current_user.id}, "
            f"file={request.lessonplan_filename}, "
            f"type={request.evaluation_type}"
        )

        # 결과 파일명 생성
        analysis_filename = (
            f"{request.lessonplan_filename}.md"
        )

        return RunEvaluationResponse(
            username=current_user.username,
            lessonplan_filename=request.lessonplan_filename,
            analysis_filename=analysis_filename,
            evaluation_type=request.evaluation_type,
            result_summary=result.get("feedback", ""),
            latency_ms=result.get("latency_ms"),
        )

    except ValueError as e:
        logger.warning(
            f"평가 실행 실패 (잘못된 요청): {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(
            f"평가 실행 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="평가 실행 중 오류가 발생했습니다."
        )


@router.get(
    "/{filename}",
    response_model=GetEvaluationResponse,
    summary="평가 결과 조회",
    description="저장된 평가 결과를 조회합니다.",
)
async def get_evaluation(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """
    평가 결과 조회

    Args:
        filename: 분석 결과 파일명
        current_user: 현재 로그인한 사용자

    Returns:
        평가 결과 내용

    Raises:
        HTTPException: 파일 없음 또는 조회 실패
    """
    try:
        storage_service = AnalysisStorageService()

        # 파일 읽기
        content = storage_service.get_analysis(
            user_id=current_user.id,
            lessonplan_filename=filename,
        )

        if not content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="평가 결과를 찾을 수 없습니다."
            )

        # 파일 크기 계산
        file_size = len(content.encode('utf-8'))

        return GetEvaluationResponse(
            filename=filename,
            content=content,
            file_size=file_size,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"평가 결과 조회 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="결과 조회 중 오류가 발생했습니다."
        )
