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

from app.db import get_db
from app.models.users import User
from app.schemas.users import UserResponse, UserLogin
from app.services.auth_service import AuthService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
        )

    auth_service = AuthService(db)
    user = await auth_service.get_user_by_id(user_id)

    if not user:
        # 세션은 있지만 사용자가 없는 경우
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다.",
        )

    return current_user


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


# T024: POST /auth/login - 로그인 또는 신규 사용자 생성
@router.post("/auth/login")
async def login(
    request: Request,
    username: str = Form(...),
    nickname: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    사용자 로그인 또는 신규 사용자 생성

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

        # 세션에 사용자 ID 저장
        request.session["user_id"] = user.id
        request.session["is_admin"] = user.is_admin

        logger.info(
            f"로그인 성공: user_id={user.id}, "
            f"username={user.username}, nickname={user.nickname}"
        )

        # 관리자는 관리자 대시보드로, 일반 사용자는 홈으로
        redirect_url = "/admin" if user.is_admin else "/"
        return RedirectResponse(
            url=redirect_url, status_code=status.HTTP_302_FOUND
        )

    except Exception as e:
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

    if user_id:
        logger.info(f"로그아웃: user_id={user_id}")

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
