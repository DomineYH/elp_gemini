"""
FastAPI 애플리케이션 메인 엔트리포인트
미들웨어, 라우터, 예외 핸들러 설정
"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import (
    JSONResponse,
    HTMLResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.cors import CORSMiddleware
import logging

from app.config import settings
from app.utils.logging import setup_logging
from app.middleware import AuthMiddleware

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
@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행"""
    logger.info("애플리케이션 시작...")

    # 데이터베이스 초기화 (개발 모드에서만)
    if settings.DEBUG:
        from app.db import init_db

        await init_db()
        logger.info("데이터베이스 초기화 완료")

    # 평가 기준 컨텍스트 Provider 초기화
    from app.services.criteria_context_provider import (
        criteria_context_provider,
    )

    await criteria_context_provider.initialize()
    logger.info("평가 기준 컨텍스트 Provider 초기화 완료")


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
from app.routers import auth, user_docs, qna, eval, admin
from app.routers.admin import criteria
from fastapi.responses import RedirectResponse

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


app.include_router(auth.router, tags=["인증"])
app.include_router(user_docs.router, tags=["문서"])
app.include_router(qna.router, tags=["QnA"])
app.include_router(eval.router, tags=["평가"])
app.include_router(admin.router, tags=["관리자"])
app.include_router(criteria.router, tags=["관리자", "평가기준"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
