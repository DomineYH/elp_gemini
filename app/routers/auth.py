"""
인증 라우터
로그인, 로그아웃, 현재 사용자 정보 엔드포인트
"""
import logging

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
from starlette.datastructures import URL

from app.config import settings
from app.constants import (
    PRESERVICE_UNIVERSITY_REGIONS,
    TEACHER_REGIONS,
)
from app.db import get_db
from app.dependencies import get_current_user
from app.models.users import User
from app.rate_limit import limiter
from app.schemas.users import (
    EmailPasswordLogin,
    PreserviceTeacherRegistration,
    TeacherRegistration,
    UserResponse,
    normalize_email_address,
)
from app.services.auth_service import AuthService
from app.utils.logging import log_auth_event

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


USER_ROLE_LABELS = {
    "teacher": "교사",
    "preservice_teacher": "예비교사",
}
INVALID_USER_CREDENTIALS_MESSAGE = (
    "이메일 또는 비밀번호가 올바르지 않습니다."
)


def _register_context(
    request: Request,
    *,
    email: str = "",
    selected_role: str = "teacher",
    error: str | None = None,
    teacher_region: str = "",
    teacher_career_years: str = "",
    preservice_university_region: str = "",
    preservice_grade: str = "",
) -> dict:
    """Build template context for the regular-user registration form."""
    return {
        "request": request,
        "error": error,
        "email": normalize_email_address(email),
        "selected_role": selected_role,
        "teacher_regions": TEACHER_REGIONS,
        "teacher_region": teacher_region,
        "teacher_career_years": teacher_career_years,
        "preservice_university_regions": (
            PRESERVICE_UNIVERSITY_REGIONS
        ),
        "preservice_university_region": (
            preservice_university_region
        ),
        "preservice_grade": preservice_grade,
    }


def _login_context(
    request: Request,
    *,
    email: str = "",
    error: str | None = None,
) -> dict:
    """Build template context for the regular-user login form."""
    return {
        "request": request,
        "error": error,
        "email": normalize_email_address(email),
    }


def _set_user_session(request: Request, user: User) -> None:
    """Clear fixation-prone session state and store fresh user identity."""
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["is_admin"] = user.is_admin
    request.session["username"] = user.username
    request.session["nickname"] = user.nickname


async def _get_regular_user_by_email(
    auth_service: AuthService,
    email: str,
) -> User | None:
    """Use Lane B regular-user lookup when present, else safe fallback."""
    if hasattr(auth_service, "get_regular_user_by_email"):
        return await auth_service.get_regular_user_by_email(email)

    user = await auth_service.get_user_by_email(email)
    if user and user.is_admin:
        return None
    return user


async def _authenticate_regular_user(
    auth_service: AuthService,
    email: str,
    password: str,
) -> User | None:
    """Use Lane B password auth when present, else verify directly."""
    if hasattr(auth_service, "authenticate_regular_user"):
        return await auth_service.authenticate_regular_user(
            email, password
        )

    user = await _get_regular_user_by_email(auth_service, email)
    if not user or not user.hashed_password:
        return None
    if not auth_service.verify_password(password, user.hashed_password):
        return None
    return user


def _validate_login_form(email: str, password: str) -> tuple[str, str]:
    """Normalize and validate login form data."""
    if EmailPasswordLogin is not None:
        login_data = EmailPasswordLogin(
            email=email,
            password=password,
        )
        return str(login_data.email), login_data.password

    normalized_email = normalize_email_address(email)
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("유효한 이메일 주소를 입력해주세요.")
    if not password:
        raise ValueError("비밀번호를 입력해주세요.")
    return normalized_email, password


def _validation_error_message(exc: Exception) -> str:
    """Convert schema/form validation exceptions into a safe message."""
    if isinstance(exc, ValidationError):
        first_error = exc.errors()[0] if exc.errors() else {}
        message = first_error.get("msg", "입력값을 확인해주세요.")
        return str(message).removeprefix("Value error, ")
    return str(exc) or "입력값을 확인해주세요."


def _redirect_to_register(email: str) -> RedirectResponse:
    """Redirect unregistered regular users into the registration flow."""
    url = str(URL("/register").include_query_params(email=email))
    return RedirectResponse(
        url=url,
        status_code=status.HTTP_303_SEE_OTHER,
    )


async def _register_teacher(
    auth_service: AuthService,
    *,
    email: str,
    password: str,
    teacher_region: str | None,
    teacher_career_years: str | None,
) -> User:
    """Validate teacher form data and delegate creation to AuthService."""
    try:
        career_years = int(teacher_career_years or "")
    except ValueError as exc:
        raise ValueError("경력 연수는 숫자로 입력해주세요.") from exc

    payload = {
        "email": email,
        "role": "teacher",
        "teacher_region": teacher_region or "",
        "teacher_career_years": career_years,
        "password": password,
    }
    registration = TeacherRegistration(**payload)
    payload = registration.model_dump()

    return await auth_service.register_teacher(
        email=payload["email"],
        password=payload["password"],
        teacher_region=payload["teacher_region"],
        teacher_career_years=payload["teacher_career_years"],
    )


async def _register_preservice_teacher(
    auth_service: AuthService,
    *,
    email: str,
    password: str,
    preservice_university_region: str | None,
    preservice_grade: str | None,
) -> User:
    """Validate preservice form data and delegate creation to AuthService."""
    try:
        grade = int(preservice_grade or "")
    except ValueError as exc:
        raise ValueError("학년은 숫자로 입력해주세요.") from exc

    payload = {
        "email": email,
        "role": "preservice_teacher",
        "preservice_university_region": (
            preservice_university_region or ""
        ),
        "preservice_grade": grade,
        "password": password,
    }
    registration = PreserviceTeacherRegistration(**payload)
    payload = registration.model_dump()

    return await auth_service.register_preservice_teacher(
        email=payload["email"],
        password=payload["password"],
        preservice_university_region=(
            payload["preservice_university_region"]
        ),
        preservice_grade=payload["preservice_grade"],
    )


# T030: GET /login - 로그인 페이지 렌더링
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, email: str = ""):
    """로그인 페이지"""
    # 이미 로그인한 경우 대시보드로 리다이렉트
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "user/login.html", _login_context(request, email=email)
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, email: str = ""):
    """일반 사용자 등록 페이지"""
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "user/register.html",
        _register_context(request, email=email),
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
        "user/login_admin.html", {"request": request}
    )


# 사용자 로그인 (이메일 + 비밀번호 기반)
@router.post("/auth/login/user")
@limiter.limit(settings.USER_LOGIN_RATE_LIMIT)
async def login_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    일반 사용자 로그인 (이메일 + 비밀번호 기반).

    등록되지 않은 이메일은 등록 화면으로 이동한다. 기존 초대코드
    인증 메서드와 /auth/login 하위 호환 라우트는 삭제하지 않는다.
    """
    try:
        normalized_email, password = _validate_login_form(
            email, password
        )
    except (ValueError, ValidationError) as exc:
        return templates.TemplateResponse(
            "user/login.html",
            _login_context(
                request,
                email=email,
                error=_validation_error_message(exc),
            ),
            status_code=400,
        )

    try:
        auth_service = AuthService(db)
        existing_user = await _get_regular_user_by_email(
            auth_service, normalized_email
        )
        if not existing_user:
            return _redirect_to_register(normalized_email)

        user = await _authenticate_regular_user(
            auth_service, normalized_email, password
        )
        if not user:
            log_auth_event(
                "login",
                username=normalized_email,
                success=False,
                reason="Invalid regular-user credentials",
            )
            return templates.TemplateResponse(
                "user/login.html",
                _login_context(
                    request,
                    email=normalized_email,
                    error=INVALID_USER_CREDENTIALS_MESSAGE,
                ),
                status_code=401,
            )

        _set_user_session(request, user)
        log_auth_event(
            "login",
            user_id=user.id,
            username=normalized_email,
            success=True,
        )
        logger.info(
            f"사용자 로그인 성공: "
            f"user_id={user.id}, email={normalized_email}"
        )

        return RedirectResponse(
            url="/", status_code=status.HTTP_302_FOUND
        )

    except ValueError as e:
        return templates.TemplateResponse(
            "user/login.html",
            _login_context(
                request,
                email=normalized_email,
                error=str(e),
            ),
            status_code=400,
        )
    except Exception as e:
        log_auth_event(
            "login",
            username=normalized_email,
            success=False,
            reason=str(e),
        )
        logger.error(f"사용자 로그인 처리 중 오류: {str(e)}", exc_info=True)
        return templates.TemplateResponse(
            "user/login.html",
            _login_context(
                request,
                email=normalized_email,
                error="로그인 처리 중 오류가 발생했습니다. "
                "다시 시도해주세요.",
            ),
            status_code=500,
        )


@router.post("/auth/register")
async def register_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str | None = Form(None),
    role: str = Form(...),
    teacher_region: str | None = Form(None),
    teacher_career_years: str | None = Form(None),
    preservice_university_region: str | None = Form(None),
    preservice_grade: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """일반 사용자 등록 후 자동 로그인."""
    normalized_email = normalize_email_address(email)
    selected_role = role if role in USER_ROLE_LABELS else "teacher"

    def render_error(message: str, status_code: int = 400):
        return templates.TemplateResponse(
            "user/register.html",
            _register_context(
                request,
                email=normalized_email,
                selected_role=selected_role,
                error=message,
                teacher_region=teacher_region or "",
                teacher_career_years=teacher_career_years or "",
                preservice_university_region=(
                    preservice_university_region or ""
                ),
                preservice_grade=preservice_grade or "",
            ),
            status_code=status_code,
        )

    if password_confirm is not None and password != password_confirm:
        return render_error("비밀번호 확인이 일치하지 않습니다.")

    if role not in USER_ROLE_LABELS:
        return render_error("유효하지 않은 사용자 유형입니다.")

    try:
        auth_service = AuthService(db)
        existing_user = await _get_regular_user_by_email(
            auth_service, normalized_email
        )
        if existing_user:
            return render_error(
                "이미 등록된 이메일입니다. 로그인해주세요.",
                status_code=409,
            )

        if role == "teacher":
            user = await _register_teacher(
                auth_service,
                email=normalized_email,
                password=password,
                teacher_region=teacher_region,
                teacher_career_years=teacher_career_years,
            )
        else:
            user = await _register_preservice_teacher(
                auth_service,
                email=normalized_email,
                password=password,
                preservice_university_region=(
                    preservice_university_region
                ),
                preservice_grade=preservice_grade,
            )

        _set_user_session(request, user)
        log_auth_event(
            "register",
            user_id=user.id,
            username=normalized_email,
            success=True,
        )
        logger.info(
            f"사용자 등록 성공: "
            f"user_id={user.id}, role={role}, email={normalized_email}"
        )

        return RedirectResponse(
            url="/", status_code=status.HTTP_302_FOUND
        )

    except (ValueError, ValidationError) as exc:
        return render_error(_validation_error_message(exc))
    except Exception as exc:
        log_auth_event(
            "register",
            username=normalized_email,
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
# Issue #6: lockout 상태도 외부 응답은 INVALID_ADMIN_CREDENTIALS_MESSAGE 로 통일.
# 별도의 lockout 메시지는 외부에 노출되지 않으므로 상수로 보존하지 않는다.


# 관리자 로그인 (ID + 비밀번호 기반) — Issue #5 brute-force 방어
@router.post("/auth/login/admin")
@limiter.limit(settings.ADMIN_LOGIN_RATE_LIMIT)
async def login_admin(
    request: Request,
    admin_id: str = Form(...),
    password: str = Form(...),
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
            return templates.TemplateResponse(
                "user/login_admin.html",
                {
                    "request": request,
                    "error": INVALID_ADMIN_CREDENTIALS_MESSAGE,
                },
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
            {
                "request": request,
                "error": "로그인 처리 중 오류가 발생했습니다. "
                "다시 시도해주세요.",
            },
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

    Issue #10 이후 일반 사용자 인증은 이메일+비밀번호 또는 보존된
    초대코드 서비스 경로만 허용한다. 이 레거시 엔드포인트는 임의의
    passwordless 세션 생성을 막기 위해 더 이상 인증을 수행하지 않는다.
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
            error="이메일과 비밀번호로 로그인해주세요.",
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
