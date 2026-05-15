"""
FastAPI 애플리케이션 메인 엔트리포인트
미들웨어, 라우터, 예외 핸들러 설정
"""
import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.db import engine
from app.middleware import AuthMiddleware
from app.migrations import (
    drop_invite_codes_table,
    ensure_app_state_table,
    ensure_criteria_display_alias_column,
    ensure_criteria_file_path_column,
    ensure_lessonplan_uploads_table,
    ensure_user_profiles_table,
    ensure_users_lockout_columns,
    rename_chat_session_in_service_teacher_label,
)
from app.rate_limit import limiter
from app.utils.logging import setup_logging

# 로깅 설정
setup_logging(debug=settings.DEBUG)
logger = logging.getLogger(__name__)

# FastAPI 앱 인스턴스
app = FastAPI(
    title="AI RAG Document Evaluation & QnA Platform",
    description="문서 평가 및 질문답변 플랫폼",
    version="0.1.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# Rate limiter (Issue #5: 관리자 로그인 brute-force 방어)
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded, _rate_limit_exceeded_handler
)

# CORS 미들웨어 (T013)
# 역순 실행: 나중에 추가한 것이 먼저 실행됨
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 전역 인증 미들웨어 (T095)
# SessionMiddleware 이후 실행 (세션 데이터 확인)
app.add_middleware(AuthMiddleware)

# 세션 미들웨어 (T012)
# 가장 먼저 실행되어야 함 (세션 데이터 로드)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie=settings.SESSION_COOKIE_NAME,
    max_age=settings.SESSION_MAX_AGE,
    same_site=settings.SESSION_SAME_SITE,
    https_only=(
        settings.SESSION_HTTPS_ONLY and not settings.DEBUG
    ),
)

# 정적 파일 및 템플릿 설정 (T016)
app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static",
)
# Note: /files 정적 마운트 제거 (보안 강화)
# 파일 다운로드는 /docs/{document_id}/download 엔드포인트 사용
templates = Jinja2Templates(directory="app/templates")


# 커스텀 예외 핸들러 (T015)
@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request, exc: HTTPException
):
    """HTTP 예외 핸들러"""
    logger.warning(
        f"HTTP {exc.status_code}: {exc.detail} - "
        f"Path: {request.url.path}"
    )

    # HTML 요청 여부 확인
    accept = request.headers.get("accept", "")
    is_html_request = "text/html" in accept.lower()

    # 401/403 오류이고 HTML 요청인 경우 /login 리다이렉트
    if exc.status_code in (401, 403) and is_html_request:
        logger.info(
            f"인증/권한 오류 ({exc.status_code}) → "
            f"/login 리다이렉트"
        )
        return RedirectResponse(
            url="/login", status_code=302
        )

    # API 요청인 경우 JSON 응답
    if request.url.path.startswith("/api") or not is_html_request:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    # 웹 요청인 경우 HTML 응답
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "status_code": exc.status_code,
            "detail": exc.detail,
        },
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def general_exception_handler(
    request: Request, exc: Exception
):
    """일반 예외 핸들러"""
    logger.error(
        f"처리되지 않은 예외: {str(exc)} - "
        f"Path: {request.url.path}",
        exc_info=True,
    )

    # API 요청인 경우 JSON 응답
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=500,
            content={"detail": "내부 서버 오류가 발생했습니다."},
        )

    # 웹 요청인 경우 HTML 응답
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "status_code": 500,
            "detail": "내부 서버 오류가 발생했습니다.",
        },
        status_code=500,
    )


# 라이프사이클 이벤트
async def _drop_legacy_invite_codes_table_if_enabled(db_engine) -> bool:
    """
    명시적 운영 승인 설정이 켜진 경우에만 레거시 invite_codes 테이블을 삭제한다.

    일반 앱 시작은 데이터 보존/롤백 가능성을 위해 파괴적 DDL을 수행하지
    않는다. 물리 삭제가 필요한 환경은 백업/보존 정책 확인 후
    DROP_LEGACY_INVITE_CODES_TABLE=true 로 opt-in 해야 한다.
    """
    if not settings.DROP_LEGACY_INVITE_CODES_TABLE:
        logger.info(
            "invite_codes 테이블 삭제 비활성화: "
            "DROP_LEGACY_INVITE_CODES_TABLE=false"
        )
        return False

    invite_codes_dropped = await drop_invite_codes_table(db_engine)
    if invite_codes_dropped:
        logger.info("invite_codes 테이블이 자동 제거되었습니다.")
    return invite_codes_dropped


_background_tasks: set[asyncio.Task] = set()


async def _run_criteria_reconcile_in_background():
    """Schedule reconcile as a non-blocking task."""
    from app.db import async_session_maker
    from app.repositories.app_state_repository import AppStateRepository
    from app.repositories.criteria_repository import CriteriaRepository
    from app.services.criteria_manifest_service import CriteriaManifestService
    from app.services.criteria_reconciliation_service import (
        CriteriaReconciliationService,
    )
    from app.services.criteria_vector_service import CriteriaVectorService

    async def _task():
        try:
            async with async_session_maker() as db:
                svc = CriteriaReconciliationService(
                    app_state_repo=AppStateRepository(db=db),
                    manifest_service=CriteriaManifestService(),
                    criteria_repo=CriteriaRepository(db=db),
                    vector_service=CriteriaVectorService(),
                )
                result = await svc.reconcile()
                await db.commit()
                logger.info(
                    "startup reconcile 결과: ok=%s skipped=%s count=%d err=%s",
                    result.ok, result.skipped, result.count, result.error,
                )
        except Exception:
            logger.exception("startup reconcile 실패")

    task = asyncio.create_task(_task())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행"""
    logger.info("애플리케이션 시작...")

    patched = await ensure_criteria_file_path_column(engine)
    if patched:
        logger.info("criteria.file_path 컬럼이 자동 복구되었습니다.")

    alias_patched = await ensure_criteria_display_alias_column(engine)
    if alias_patched:
        logger.info(
            "criteria.display_alias 컬럼이 자동 추가되었습니다."
        )

    created = await ensure_app_state_table(engine)
    if created:
        logger.info("app_state 테이블이 자동 생성되었습니다.")

    lockout_patched = await ensure_users_lockout_columns(engine)
    if lockout_patched:
        logger.info(
            "users 테이블 lockout 컬럼이 자동 복구되었습니다."
        )

    profiles_patched = await ensure_user_profiles_table(engine)
    if profiles_patched:
        logger.info(
            "user_profiles 테이블이 자동 생성되었습니다."
        )

    uploads_patched = await ensure_lessonplan_uploads_table(engine)
    if uploads_patched:
        logger.info(
            "lessonplan_uploads / analysis_reports.upload_id 자동 적용"
        )

    renamed = await rename_chat_session_in_service_teacher_label(engine)
    if renamed:
        logger.info(
            "chat_sessions.user_type '현직교사' → '교사' 갱신: %d 행",
            renamed,
        )

    # 데이터베이스 초기화 (개발 모드에서만)
    if settings.DEBUG:
        from app.db import init_db

        await init_db()
        logger.info("데이터베이스 초기화 완료")

    await _drop_legacy_invite_codes_table_if_enabled(engine)

    if settings.CRITERIA_CLOUD_RECONCILE_ENABLED:
        await _run_criteria_reconcile_in_background()


@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 실행"""
    logger.info("애플리케이션 종료...")


# T120: Health check 엔드포인트
@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "debug": settings.DEBUG,
    }


# 라우터 등록
from app.routers import (  # noqa: E402
    auth,
    evaluations,
    lessonplan_analysis,
    qna,
    views,
)
from app.routers.admin import exports as admin_exports  # noqa: E402
from app.routers.admin import router as admin_router  # noqa: E402


# 루트 엔드포인트 - 역할 기반 리다이렉트
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """
    루트 페이지
    - 관리자: /admin/dashboard로 리다이렉트
    - 일반 사용자: /docs로 리다이렉트 (사용자 대시보드)
    - 미인증: /login으로 리다이렉트
    """
    user_id = request.session.get("user_id")
    is_admin = request.session.get("is_admin", False)

    if user_id:
        # 로그인한 경우 - 역할에 따라 리다이렉트
        if is_admin:
            # 관리자 → 관리자 대시보드
            return RedirectResponse(
                url="/admin/dashboard", status_code=302
            )
        else:
            # 일반 사용자 → 사용자 대시보드
            return RedirectResponse(
                url="/dashboard", status_code=302
            )
    else:
        # 미인증 → 로그인 페이지
        return RedirectResponse(url="/login", status_code=302)


# 라우터 등록
app.include_router(auth.router, tags=["인증"])
app.include_router(qna.router)
app.include_router(evaluations.router)
app.include_router(lessonplan_analysis.router)
app.include_router(views.router)
app.include_router(admin_router)
app.include_router(admin_exports.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
