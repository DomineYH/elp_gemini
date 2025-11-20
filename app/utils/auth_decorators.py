"""
인증 관련 데코레이터 및 헬퍼 함수

FastAPI에서는 Depends를 사용한 의존성 주입이 표준이지만,
추가적인 유틸리티 함수를 제공합니다.

Note: 현재 AuthMiddleware가 전역 인증을 처리하고 있으므로,
이 모듈은 선택적으로 사용할 수 있습니다.
"""

from functools import wraps
from typing import Callable, Optional
import logging

from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def require_auth(
    redirect_url: str = "/login",
    allow_api: bool = True,
):
    """
    인증 필수 데코레이터

    FastAPI 엔드포인트에 적용하여 인증을 강제합니다.
    Note: AuthMiddleware가 이미 전역 인증을 처리하므로
    추가 보안 레이어가 필요한 경우에만 사용하세요.

    Args:
        redirect_url: 미인증 시 리다이렉트 URL
        allow_api: API 요청은 통과 허용 (401 응답)

    Returns:
        데코레이터 함수

    Example:
        @app.get("/protected")
        @require_auth()
        async def protected_route(request: Request):
            return {"message": "Protected"}
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Request 객체 찾기
            request: Optional[Request] = kwargs.get(
                "request"
            ) or next(
                (arg for arg in args if isinstance(arg, Request)),
                None,
            )

            if not request:
                logger.warning(
                    "require_auth: Request 객체를 찾을 수 없음"
                )
                return await func(*args, **kwargs)

            # 세션 확인
            user_id = request.session.get("user_id")

            if not user_id:
                # 인증 실패
                logger.warning(
                    f"require_auth: 인증 실패 - "
                    f"path={request.url.path}"
                )

                # HTML vs API 요청 판단
                accept = request.headers.get("accept", "")
                is_html = "text/html" in accept.lower()

                if is_html:
                    # HTML 요청 → 리다이렉트
                    return RedirectResponse(
                        url=redirect_url, status_code=302
                    )
                elif allow_api:
                    # API 요청 → 401 JSON
                    return JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={
                            "detail": "로그인이 필요합니다."
                        },
                    )
                else:
                    # API 요청도 리다이렉트
                    return RedirectResponse(
                        url=redirect_url, status_code=302
                    )

            # 인증 성공 → 함수 실행
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_admin(redirect_url: str = "/login"):
    """
    관리자 권한 필수 데코레이터

    Note: Depends(get_current_admin) 사용을 권장합니다.

    Args:
        redirect_url: 권한 없음 시 리다이렉트 URL

    Returns:
        데코레이터 함수

    Example:
        @app.get("/admin/dashboard")
        @require_admin()
        async def admin_dashboard(request: Request):
            return {"message": "Admin Dashboard"}
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Request 객체 찾기
            request: Optional[Request] = kwargs.get(
                "request"
            ) or next(
                (arg for arg in args if isinstance(arg, Request)),
                None,
            )

            if not request:
                logger.warning(
                    "require_admin: Request 객체를 찾을 수 없음"
                )
                return await func(*args, **kwargs)

            # 세션 확인
            user_id = request.session.get("user_id")
            is_admin = request.session.get("is_admin", False)

            if not user_id or not is_admin:
                # 권한 없음
                logger.warning(
                    f"require_admin: 권한 없음 - "
                    f"user_id={user_id}, "
                    f"is_admin={is_admin}, "
                    f"path={request.url.path}"
                )

                # HTML vs API 요청 판단
                accept = request.headers.get("accept", "")
                is_html = "text/html" in accept.lower()

                if is_html:
                    # HTML 요청 → 리다이렉트
                    return RedirectResponse(
                        url=redirect_url, status_code=302
                    )
                else:
                    # API 요청 → 403 JSON
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={
                            "detail": "관리자 권한이 필요합니다."
                        },
                    )

            # 권한 확인 → 함수 실행
            return await func(*args, **kwargs)

        return wrapper

    return decorator


# 편의 함수 (Depends와 함께 사용)
async def verify_session(request: Request) -> bool:
    """
    세션 유효성 검증 헬퍼 함수

    Args:
        request: Request 객체

    Returns:
        세션 유효 여부
    """
    user_id = request.session.get("user_id")
    return user_id is not None


async def verify_admin_session(request: Request) -> bool:
    """
    관리자 세션 유효성 검증 헬퍼 함수

    Args:
        request: Request 객체

    Returns:
        관리자 세션 유효 여부
    """
    user_id = request.session.get("user_id")
    is_admin = request.session.get("is_admin", False)
    return user_id is not None and is_admin
