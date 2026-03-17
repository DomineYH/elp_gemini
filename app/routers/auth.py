"""
인증 라우터
로그인, 로그아웃, 현재 사용자 정보 엔드포인트
"""
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Request,
    Form,
)
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.constants import USER_TYPES
from app.db import get_db
from app.models.users import User
from app.schemas.users import UserResponse, UserLogin
from app.services.auth_service import AuthService
from app.utils.logging import log_auth_event
from app.dependencies import get_current_user, get_current_admin

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)




# T030: GET /login - 로그인 페이지 렌더링
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """로그인 페이지"""
    # 이미 로그인한 경우 대시보드로 리다이렉트
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "user/login.html", {"request": request}
    )


# 사용자 로그인 (드롭다운 선택 기반)
@router.post("/auth/login/user")
async def login_user(
    request: Request,
    user_type: str = Form(...),
    invite_code: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    사용자 로그인 (드롭다운 선택 + 초대 코드 기반)

    사용자 유형(1학년, 2학년, 3학년, 4학년, 현직교사)과
    초대 코드를 사용하여 로그인합니다.

    Args:
        request: Request 객체
        user_type: 사용자 유형 (1학년, 2학년, 3학년, 4학년, 현직교사)
        invite_code: 초대 코드
        db: 데이터베이스 세션

    Returns:
        리다이렉트 응답
    """
    if user_type not in USER_TYPES:
        return templates.TemplateResponse(
            "user/login.html",
            {
                "request": request,
                "error": "유효하지 않은 사용자 유형입니다.",
                "active_tab": "user",
            },
            status_code=400,
        )

    try:
        auth_service = AuthService(db)
        user = await auth_service.authenticate_user_with_code(
            user_type, invite_code
        )

        # 세션 고정 공격 방지: 기존 세션 클리어
        request.session.clear()

        # 새 세션에 사용자 정보 저장
        request.session["user_id"] = user.id
        request.session["is_admin"] = user.is_admin
        request.session["username"] = user.username
        request.session["nickname"] = user.nickname
        request.session["invite_code"] = invite_code.upper()

        # 로그인 성공 로깅
        log_auth_event(
            "login",
            user_id=user.id,
            username=user.username,
            success=True,
        )
        masked = invite_code[:2] + "****"
        logger.info(
            f"사용자 로그인 성공: "
            f"user_id={user.id}, code={masked}"
        )

        return RedirectResponse(
            url="/", status_code=status.HTTP_302_FOUND
        )

    except ValueError as e:
        return templates.TemplateResponse(
            "user/login.html",
            {
                "request": request,
                "error": str(e),
                "active_tab": "user",
            },
            status_code=400,
        )
    except Exception as e:
        log_auth_event(
            "login",
            username=user_type,
            success=False,
            reason=str(e),
        )
        logger.error(f"사용자 로그인 처리 중 오류: {str(e)}", exc_info=True)
        return templates.TemplateResponse(
            "user/login.html",
            {
                "request": request,
                "error": "로그인 처리 중 오류가 발생했습니다. "
                "다시 시도해주세요.",
                "active_tab": "user",
            },
            status_code=500,
        )


# 관리자 로그인 (ID + 비밀번호 기반)
@router.post("/auth/login/admin")
async def login_admin(
    request: Request,
    admin_id: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 로그인 (ID + 비밀번호 기반)

    관리자 ID와 비밀번호를 사용하여 인증합니다.

    Args:
        request: Request 객체
        admin_id: 관리자 ID
        password: 비밀번호
        db: 데이터베이스 세션

    Returns:
        리다이렉트 응답
    """
    try:
        auth_service = AuthService(db)
        user = await auth_service.authenticate_admin(admin_id, password)

        if not user:
            log_auth_event(
                "login",
                username=admin_id,
                success=False,
                reason="Invalid credentials",
            )
            return templates.TemplateResponse(
                "user/login.html",
                {
                    "request": request,
                    "error": "관리자 ID 또는 비밀번호가 올바르지 않습니다.",
                    "active_tab": "admin",
                },
                status_code=401,
            )

        # 세션 고정 공격 방지: 기존 세션 클리어
        request.session.clear()

        # 새 세션에 사용자 정보 저장
        request.session["user_id"] = user.id
        request.session["is_admin"] = user.is_admin
        request.session["username"] = user.username
        request.session["nickname"] = user.nickname

        # 로그인 성공 로깅
        log_auth_event(
            "login",
            user_id=user.id,
            username=user.username,
            success=True,
        )
        logger.info(
            f"관리자 로그인 성공: "
            f"user_id={user.id}, admin_id={admin_id}"
        )

        return RedirectResponse(
            url="/admin/dashboard", status_code=status.HTTP_302_FOUND
        )

    except Exception as e:
        log_auth_event(
            "login",
            username=admin_id,
            success=False,
            reason=str(e),
        )
        logger.error(f"관리자 로그인 처리 중 오류: {str(e)}", exc_info=True)
        return templates.TemplateResponse(
            "user/login.html",
            {
                "request": request,
                "error": "로그인 처리 중 오류가 발생했습니다. "
                "다시 시도해주세요.",
                "active_tab": "admin",
            },
            status_code=500,
        )


# T024: POST /auth/login - 기존 로그인 (하위 호환성 유지)
@router.post("/auth/login")
async def login(
    request: Request,
    username: str = Form(...),
    nickname: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    사용자 로그인 또는 신규 사용자 생성 (하위 호환성)

    사용자 식별 로직:
    - username과 nickname이 모두 일치 → 기존 사용자로 로그인
    - 둘 중 하나라도 다름 → 새로운 사용자 생성 후 로그인

    Args:
        request: Request 객체
        username: 사용자 ID
        nickname: 닉네임
        db: 데이터베이스 세션

    Returns:
        리다이렉트 응답
    """
    try:
        auth_service = AuthService(db)
        user = await auth_service.authenticate_user(username, nickname)

        # 세션 고정 공격 방지: 기존 세션 클리어 (Task 2.2)
        # 로그인 성공 시 새로운 세션 ID를 생성합니다.
        request.session.clear()

        # 새 세션에 사용자 정보 저장
        request.session["user_id"] = user.id
        request.session["is_admin"] = user.is_admin
        request.session["username"] = user.username
        request.session["nickname"] = user.nickname

        # 로그인 성공 로깅
        log_auth_event(
            "login",
            user_id=user.id,
            username=user.username,
            success=True,
        )
        logger.info(
            f"로그인 성공 (세션 재발급): "
            f"user_id={user.id}, "
            f"username={user.username}, nickname={user.nickname}"
        )

        # 역할 기반 리다이렉트
        if user.is_admin:
            redirect_url = "/admin/dashboard"
        else:
            redirect_url = "/"

        return RedirectResponse(
            url=redirect_url, status_code=status.HTTP_302_FOUND
        )

    except Exception as e:
        # 로그인 실패 로깅
        log_auth_event(
            "login",
            username=username,
            success=False,
            reason=str(e),
        )
        logger.error(f"로그인 처리 중 오류: {str(e)}", exc_info=True)
        return templates.TemplateResponse(
            "user/login.html",
            {
                "request": request,
                "error": "로그인 처리 중 오류가 발생했습니다. "
                "다시 시도해주세요.",
            },
            status_code=500,
        )


# T025: POST /auth/logout - 로그아웃 처리
@router.post("/auth/logout")
async def logout(request: Request):
    """
    사용자 로그아웃

    Args:
        request: Request 객체

    Returns:
        리다이렉트 응답
    """
    user_id = request.session.get("user_id")
    username = request.session.get("username")

    if user_id:
        # 로그아웃 로깅
        log_auth_event(
            "logout",
            user_id=user_id,
            username=username,
            success=True,
        )
        logger.info(f"로그아웃: user_id={user_id}")

        # Vector Store 정리
        try:
            from app.services.file_search_service import FileSearchService
            file_search_service = FileSearchService()
            store_name = f"user-{username}-store"
            await file_search_service.delete_store_by_display_name(store_name)
        except Exception as e:
            logger.warning(f"로그아웃 시 스토어 정리 실패: {str(e)}")

    request.session.clear()

    return RedirectResponse(
        url="/login", status_code=status.HTTP_302_FOUND
    )


# T026: GET /auth/me - 현재 사용자 정보
@router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    현재 로그인한 사용자 정보 조회

    Args:
        current_user: 현재 사용자

    Returns:
        UserResponse 객체
    """
    return current_user
