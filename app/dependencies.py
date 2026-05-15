"""
의존성 주입 설정
FastAPI 의존성 함수 모음
"""
import logging
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.users import User
from app.services.auth_service import AuthService
from app.utils.logging import log_auth_event

logger = logging.getLogger(__name__)


# T022: get_current_user 의존성
async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """
    현재 로그인한 사용자 가져오기

    Args:
        request: FastAPI Request 객체
        db: 데이터베이스 세션

    Returns:
        User 객체

    Raises:
        HTTPException: 인증되지 않은 경우
    """
    user_id = request.session.get("user_id")

    if not user_id:
        log_auth_event(
            "authentication_required",
            success=False,
            reason="No session",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
        )

    auth_service = AuthService(db)
    user = await auth_service.get_user_by_id(user_id)

    if not user:
        # 세션은 있지만 사용자가 없는 경우
        log_auth_event(
            "invalid_session",
            user_id=user_id,
            success=False,
            reason="User not found",
        )
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없습니다.",
        )

    return user


# T023: get_current_admin 의존성
async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    현재 관리자 사용자 가져오기

    Args:
        current_user: 현재 사용자

    Returns:
        관리자 User 객체

    Raises:
        HTTPException: 관리자가 아닌 경우
    """
    if not current_user.is_admin:
        log_auth_event(
            "permission_denied",
            user_id=current_user.id,
            username=current_user.username,
            success=False,
            reason="Admin permission required",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다.",
        )

    return current_user


async def get_app_state_repo(db=Depends(get_db)):
    from app.repositories.app_state_repository import AppStateRepository

    return AppStateRepository(db=db)


async def require_criteria_sync_ready(
    app_state_repo=Depends(get_app_state_repo),
) -> None:
    """평가기준 동기화 상태가 ok가 아니면 503."""
    from app.repositories.app_state_repository import (
        KEY_SYNC_STATE,
        SYNC_STATE_OK,
    )

    state = await app_state_repo.get(KEY_SYNC_STATE)
    if state != SYNC_STATE_OK:
        raise HTTPException(
            status_code=503,
            detail=(
                "평가기준이 동기화 중이거나 사용할 수 없습니다. "
                "관리자 페이지에서 동기화 상태를 확인하세요."
            ),
        )
