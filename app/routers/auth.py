"""
인증 라우터
로그인, 로그아웃, 현재 사용자 정보 엔드포인트
"""
import asyncio
import logging
import secrets
import time

from fastapi import (
    APIRouter,
    Depends,
    Form,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models.users import User
from app.rate_limit import (
    check_admin_id_rate_limit,
    check_admin_ip_rate_limit,
    limiter,
)
from app.schemas.users import (
    IdPasswordLogin,
    RegularUserRegistration,
    UserResponse,
)
from app.services.auth_service import AuthService
from app.utils.logging import log_auth_event

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


async def _equalize_admin_failure_response(started_at: float) -> None:
    """관리자 실패 응답을 최소 시간까지 지연해 timing oracle 을 줄인다."""
    min_seconds = float(settings.ADMIN_LOGIN_FAILURE_MIN_SECONDS)
    if min_seconds <= 0:
        return
    remaining = min_seconds - (time.monotonic() - started_at)
    if remaining > 0:
        await asyncio.sleep(remaining)


INVALID_USER_CREDENTIALS_MESSAGE = (
    "아이디 또는 비밀번호가 올바르지 않습니다."
)


def _register_context(
    request: Request,
    *,
    user_id: str = "",
    error: str | None = None,
) -> dict:
    """Build template context for the regular-user registration form."""
    return {
        "request": request,
        "error": error,
        "user_id": user_id,
    }


def _login_context(
    request: Request,
    *,
    user_id: str = "",
    error: str | None = None,
) -> dict:
    """Build template context for the regular-user login form."""
    return {
        "request": request,
        "error": error,
        "user_id": user_id,
    }


def _set_user_session(request: Request, user: User) -> None:
    """Clear fixation-prone session state and store fresh user identity."""
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["is_admin"] = user.is_admin
    request.session["username"] = user.username
    request.session["nickname"] = user.nickname


def _validation_error_message(exc: Exception) -> str:
    """Convert schema/form validation exceptions into a safe message."""
    if isinstance(exc, ValidationError):
        first_error = exc.errors()[0] if exc.errors() else {}
        message = first_error.get("msg", "입력값을 확인해주세요.")
        return str(message).removeprefix("Value error, ")
    return str(exc) or "입력값을 확인해주세요."


# T030: GET /login - 로그인 페이지 렌더링
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """로그인 페이지"""
    # 이미 로그인한 경우 대시보드로 리다이렉트
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "user/login.html", _login_context(request)
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """일반 사용자 등록 페이지"""
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "user/register.html",
        _register_context(request),
    )


# GET /login/admin - 관리자 전용 로그인 페이지 (직접 URL 접근 시에만 노출)
# /admin/login alias도 등록해 두 URL 모두 동일 페이지로 진입 가능
@router.get("/login/admin", response_class=HTMLResponse)
@router.get(
    "/admin/login",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def login_admin_page(request: Request):
    """관리자 로그인 페이지 (URL 직접 입력 시에만 노출)"""
    # 이미 로그인한 경우 역할별 대시보드로 리다이렉트
    if request.session.get("user_id"):
        if request.session.get("is_admin"):
            return RedirectResponse(url="/admin/dashboard", status_code=302)
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "user/login_admin.html", _admin_login_context(request)
    )


# 사용자 로그인 (id + 비밀번호 기반)
@router.post("/auth/login/user")
@limiter.limit(settings.USER_LOGIN_RATE_LIMIT)
async def login_user(
    request: Request,
    user_id: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    일반 사용자 로그인 (사용자 지정 id + 비밀번호 기반).

    미등록 id 는 자격 증명 오류로 처리한다(id 열거 방지). 레거시
    /auth/login 하위 호환 차단 라우트는 삭제하지 않는다.
    """
    try:
        login_data = IdPasswordLogin(user_id=user_id, password=password)
    except ValidationError as exc:
        return templates.TemplateResponse(
            "user/login.html",
            _login_context(
                request,
                user_id=user_id,
                error=_validation_error_message(exc),
            ),
            status_code=400,
        )

    normalized_id = login_data.user_id

    try:
        auth_service = AuthService(db)
        user = await auth_service.authenticate_regular_user_by_username(
            normalized_id, login_data.password
        )
        if not user:
            log_auth_event(
                "login",
                username=normalized_id,
                success=False,
                reason="Invalid regular-user credentials",
            )
            return templates.TemplateResponse(
                "user/login.html",
                _login_context(
                    request,
                    user_id=normalized_id,
                    error=INVALID_USER_CREDENTIALS_MESSAGE,
                ),
                status_code=401,
            )

        _set_user_session(request, user)
        log_auth_event(
            "login",
            user_id=user.id,
            username=normalized_id,
            success=True,
        )
        logger.info(
            f"사용자 로그인 성공: user_id={user.id}, id={normalized_id}"
        )

        return RedirectResponse(
            url="/", status_code=status.HTTP_302_FOUND
        )

    except Exception as e:
        log_auth_event(
            "login",
            username=normalized_id,
            success=False,
            reason=str(e),
        )
        logger.error(f"사용자 로그인 처리 중 오류: {str(e)}", exc_info=True)
        return templates.TemplateResponse(
            "user/login.html",
            _login_context(
                request,
                user_id=normalized_id,
                error="로그인 처리 중 오류가 발생했습니다. "
                "다시 시도해주세요.",
            ),
            status_code=500,
        )


@router.post("/auth/register")
async def register_user(
    request: Request,
    user_id: str = Form(...),
    password: str = Form(...),
    password_confirm: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """일반 사용자 등록 후 자동 로그인 (사용자 지정 id + 비밀번호)."""

    def render_error(message: str, status_code: int = 400):
        return templates.TemplateResponse(
            "user/register.html",
            _register_context(
                request,
                user_id=user_id,
                error=message,
            ),
            status_code=status_code,
        )

    if password != (password_confirm or ""):
        return render_error("비밀번호 확인이 일치하지 않습니다.")

    try:
        registration = RegularUserRegistration(
            user_id=user_id, password=password
        )
    except ValidationError as exc:
        return render_error(_validation_error_message(exc))

    try:
        auth_service = AuthService(db)
        user = await auth_service.register_regular_user(
            user_id=registration.user_id,
            password=registration.password,
        )

        _set_user_session(request, user)
        log_auth_event(
            "register",
            user_id=user.id,
            username=user.username,
            success=True,
        )
        logger.info(
            f"사용자 등록 성공: user_id={user.id}, id={user.username}"
        )

        return RedirectResponse(
            url="/", status_code=status.HTTP_302_FOUND
        )

    except ValueError as exc:
        # 중복 아이디 등 도메인 검증 실패
        return render_error(str(exc), status_code=409)
    except Exception as exc:
        log_auth_event(
            "register",
            username=user_id,
            success=False,
            reason=str(exc),
        )
        logger.error(
            f"사용자 등록 처리 중 오류: {str(exc)}", exc_info=True
        )
        return render_error(
            "등록 처리 중 오류가 발생했습니다. 다시 시도해주세요.",
            status_code=500,
        )


INVALID_ADMIN_CREDENTIALS_MESSAGE = (
    "관리자 ID 또는 비밀번호가 올바르지 않습니다."
)
ADMIN_LOGIN_CSRF_SESSION_KEY = "admin_login_csrf_token"
ADMIN_LOGIN_CSRF_ERROR_MESSAGE = (
    "보안 확인에 실패했습니다. 로그인 페이지를 새로고침한 뒤 "
    "다시 시도해주세요."
)
# Issue #6: lockout 상태도 외부 응답은 generic admin 실패 메시지로 통일.
# 별도의 lockout 메시지는 외부에 노출되지 않으므로 상수로 보존하지 않는다.


def _ensure_admin_login_csrf_token(request: Request) -> str:
    """관리자 로그인 폼용 CSRF 토큰을 세션에 보관한다."""
    token = request.session.get(ADMIN_LOGIN_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[ADMIN_LOGIN_CSRF_SESSION_KEY] = token
    return str(token)


def _admin_login_context(
    request: Request,
    *,
    error: str | None = None,
) -> dict:
    """Build template context for the administrator login form."""
    return {
        "request": request,
        "error": error,
        "csrf_token": _ensure_admin_login_csrf_token(request),
    }


def _is_admin_login_csrf_valid(
    request: Request,
    csrf_token: str,
) -> bool:
    """세션 토큰과 폼 토큰을 상수 시간 비교한다."""
    expected = request.session.get(ADMIN_LOGIN_CSRF_SESSION_KEY)
    return bool(
        expected
        and csrf_token
        and secrets.compare_digest(str(expected), str(csrf_token))
    )


# 관리자 로그인 (ID + 비밀번호 기반) — Issue #5 brute-force 방어
@router.post("/auth/login/admin")
async def login_admin(
    request: Request,
    admin_id: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """
    관리자 로그인 (ID + 비밀번호 기반)

    Issue #5: rate limit + 계정 잠금으로 brute-force 방어.

    Args:
        request: Request 객체
        admin_id: 관리자 ID
        password: 비밀번호
        db: 데이터베이스 세션

    Returns:
        리다이렉트 응답 또는 401
    """
    if not _is_admin_login_csrf_valid(request, csrf_token):
        return templates.TemplateResponse(
            "user/login_admin.html",
            _admin_login_context(
                request,
                error=ADMIN_LOGIN_CSRF_ERROR_MESSAGE,
            ),
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # CSRF 검증을 통과한 로그인 시도만 IP/admin_id quota 를 소모한다.
    # 아래의 try/except Exception 가 HTTPException(429) 까지 삼켜 500 으로
    # 변환하지 않도록 try 블록 밖에서 호출한다.
    check_admin_ip_rate_limit(request)
    check_admin_id_rate_limit(admin_id)
    failure_started_at = time.monotonic()

    try:
        auth_service = AuthService(db)
        result = await auth_service.authenticate_admin(
            admin_id, password
        )

        # 외부 응답 통일 (issue #6) — locked / invalid 모두 동일한 401 + 메시지
        if result.locked or not result.user:
            if result.locked:
                # 내부 감사 로그는 lockout 상황을 별도 기록 (외부에는 노출 X)
                log_auth_event(
                    "lockout_attempt_external_blocked",
                    username=admin_id,
                    success=False,
                    reason="locked_response_unified_with_invalid",
                )
            else:
                log_auth_event(
                    "login",
                    username=admin_id,
                    success=False,
                    reason="Invalid credentials",
                )
            await _equalize_admin_failure_response(failure_started_at)
            return templates.TemplateResponse(
                "user/login_admin.html",
                _admin_login_context(
                    request,
                    error=INVALID_ADMIN_CREDENTIALS_MESSAGE,
                ),
                status_code=401,
            )

        user = result.user

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
        logger.error(
            f"관리자 로그인 처리 중 오류: {str(e)}", exc_info=True
        )
        return templates.TemplateResponse(
            "user/login_admin.html",
            _admin_login_context(
                request,
                error="로그인 처리 중 오류가 발생했습니다. "
                "다시 시도해주세요.",
            ),
            status_code=500,
        )


# T024: POST /auth/login - 기존 로그인 (하위 호환성 유지)
@router.post("/auth/login")
async def login(
    request: Request,
    username: str = Form(...),
    nickname: str = Form(...),
):
    """
    기존 username/nickname 로그인 엔드포인트.

    Issue #90 이후 일반 사용자 인증은 사용자 지정 id+비밀번호
    흐름만 허용한다. 이 레거시 엔드포인트는 임의의 passwordless
    세션 생성을 막기 위해 더 이상 인증을 수행하지 않는다.
    """
    log_auth_event(
        "legacy_login_blocked",
        username=username,
        success=False,
        reason="Legacy username/nickname login disabled",
    )
    return templates.TemplateResponse(
        "user/login.html",
        _login_context(
            request,
            error="아이디와 비밀번호로 로그인해주세요.",
        ),
        status_code=status.HTTP_410_GONE,
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
