"""
지도안 관리 라우터
파일 조회, 삭제 엔드포인트
"""
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from fastapi.responses import FileResponse
import logging
from pathlib import Path

from app.dependencies import get_current_user
from app.models.users import User
from app.schemas.lessonplans import (
    LessonPlanListResponse,
)
from app.services.lessonplan_storage_service import (
    LessonPlanStorageService
)

router = APIRouter(prefix="/api/lessonplans", tags=["지도안"])
logger = logging.getLogger(__name__)


@router.get(
    "",
    response_model=LessonPlanListResponse,
    summary="지도안 목록 조회",
    description="사용자의 지도안 목록을 조회합니다.",
)
async def list_lessonplans(
    current_user: User = Depends(get_current_user),
):
    """
    지도안 목록 조회

    Args:
        current_user: 현재 로그인한 사용자

    Returns:
        지도안 목록

    Raises:
        HTTPException: 조회 오류
    """
    try:
        storage_service = LessonPlanStorageService()
        lessonplans = storage_service.list_lessonplans(
            username=current_user.username
        )

        return LessonPlanListResponse(
            username=current_user.username,
            lessonplans=lessonplans,
            total_count=len(lessonplans),
        )

    except Exception as e:
        logger.error(
            f"지도안 목록 조회 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="목록 조회 중 오류가 발생했습니다."
        )


@router.get(
    "/{filename}/download",
    response_class=FileResponse,
    summary="지도안 다운로드",
    description="지도안 파일을 다운로드합니다.",
)
async def download_lessonplan(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """
    지도안 파일 다운로드

    Args:
        filename: 파일명
        current_user: 현재 로그인한 사용자

    Returns:
        파일 응답

    Raises:
        HTTPException: 파일 없음 또는 권한 오류
    """
    try:
        storage_service = LessonPlanStorageService()
        file_path = storage_service.get_lessonplan_path(
            username=current_user.username,
            filename=filename,
        )

        if not file_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="파일을 찾을 수 없습니다."
            )

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/octet-stream"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"지도안 다운로드 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="파일 다운로드 중 오류가 발생했습니다."
        )


@router.delete(
    "/{filename}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="지도안 삭제",
    description="지도안 파일을 삭제합니다.",
)
async def delete_lessonplan(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """
    지도안 파일 삭제

    Args:
        filename: 파일명
        current_user: 현재 로그인한 사용자

    Raises:
        HTTPException: 파일 없음 또는 삭제 오류
    """
    try:
        storage_service = LessonPlanStorageService()
        success = storage_service.delete_lessonplan(
            username=current_user.username,
            filename=filename,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="파일을 찾을 수 없습니다."
            )

        logger.info(
            f"지도안 삭제 성공: "
            f"user={current_user.username}, "
            f"file={filename}"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"지도안 삭제 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="파일 삭제 중 오류가 발생했습니다."
        )
