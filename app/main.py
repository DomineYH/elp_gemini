"""
FastAPI 애플리케이션 메인 엔트리포인트
미들웨어, 라우터, 예외 핸들러 설정
"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.cors import CORSMiddleware
import logging

from app.config import settings
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

# 세션 미들웨어 (T012)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie="session",
    max_age=60 * 60 * 24 * 7,  # 7일
    same_site="lax",
    https_only=not settings.DEBUG,
)

# CORS 미들웨어 (T013)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 및 템플릿 설정 (T016)
app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static",
)
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

    # API 요청인 경우 JSON 응답
    if request.url.path.startswith("/api"):
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
from fastapi.responses import RedirectResponse

# 루트 엔드포인트 - 인증 상태에 따라 리다이렉트
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """
    루트 페이지
    - 로그인한 경우: 사용자 대시보드로 리다이렉트
    - 로그인하지 않은 경우: 로그인 페이지로 리다이렉트
    """
    user_id = request.session.get("user_id")

    if user_id:
        # 로그인한 경우 - 사용자 대시보드 표시
        # user_docs 라우터의 dashboard 함수 호출
        from app.routers.user_docs import dashboard
        from app.db import get_db
        from app.routers.auth import get_current_user

        try:
            # 현재 사용자 가져오기
            db_gen = get_db()
            db = await db_gen.__anext__()
            try:
                current_user = await get_current_user(request, db)
                # 대시보드 렌더링
                response = await dashboard(request, current_user, db)
                return response
            finally:
                await db_gen.aclose()
        except HTTPException:
            # 세션은 있지만 사용자가 없는 경우 - 로그인 페이지로
            request.session.clear()
            return RedirectResponse(url="/login", status_code=302)
    else:
        # 로그인하지 않은 경우 - 로그인 페이지로
        return RedirectResponse(url="/login", status_code=302)


app.include_router(auth.router, tags=["인증"])
app.include_router(user_docs.router, tags=["문서"])
app.include_router(qna.router, tags=["QnA"])
app.include_router(eval.router, tags=["평가"])
app.include_router(admin.router, tags=["관리자"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
