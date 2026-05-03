"""
전역 인증 미들웨어

모든 HTML 요청에 대해 세션 검증을 수행하고,
인증되지 않은 요청은 /login으로 리다이렉트합니다.
"""

import logging

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.responses import Response

from app.db import async_session_maker
from app.models.users import User

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    전역 인증 미들웨어

    HTML 요청에 대해 세션 검증을 수행하고,
    인증되지 않은 요청은 /login으로 리다이렉트합니다.

    화이트리스트 경로는 인증 없이 통과합니다:
    - /login, /login/admin
    - /auth/login, /auth/login/user, /auth/login/admin, /auth/logout
    - /health
    - /static/*
    - /docs, /redoc, /openapi.json (API 문서)
    """

    # 화이트리스트 경로 (인증 불필요)
    WHITELIST_PATHS = [
        "/login",
        "/register",
        "/register/",
        # 관리자 로그인 페이지 (직접 URL 접근, 인증 전 노출 필요)
        "/login/admin",
        "/login/admin/",
        "/admin/login",
        "/admin/login/",
        # 공개 auth 엔드포인트 (접두사 /auth/ 제거, 명시적 경로만 허용)
        "/auth/login",
        "/auth/login/",
        "/auth/login/user",
        "/auth/login/user/",
        "/auth/login/admin",
        "/auth/login/admin/",
        "/auth/logout",
        "/auth/logout/",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    ]

    # 화이트리스트 경로 접두사 (하위 경로 포함)
    WHITELIST_PREFIXES = [
        "/static/",
    ]

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """
        미들웨어 디스패치 로직

        Args:
            request: 요청 객체
            call_next: 다음 미들웨어 또는 엔드포인트

        Returns:
            응답 객체 또는 리다이렉트
        """
        path = request.url.path

        # 화이트리스트 경로 확인
        if self._is_whitelisted(path):
            return await call_next(request)

        # HTML 요청인지 확인
        if not self._is_html_request(request):
            # API 요청은 통과 (401은 각 엔드포인트에서 처리)
            return await call_next(request)

        # 세션 검증
        user_id = request.session.get("user_id")
        is_admin = request.session.get("is_admin", False)

        if not user_id:
            # 인증되지 않은 HTML 요청 → /login 리다이렉트
            logger.info(
                f"인증 실패: {path} → /login 리다이렉트"
            )
            return RedirectResponse(
                url="/login", status_code=302
            )

        # DB에서 세션 유효성 검증 (Task 2.2)
        is_valid = await self._validate_session_in_db(
            user_id, is_admin
        )

        if not is_valid:
            # 무효한 세션 → 세션 정리 후 /login 리다이렉트
            logger.info(
                f"무효한 세션 정리: "
                f"user_id={user_id}, "
                f"path={path}"
            )
            request.session.clear()
            return RedirectResponse(
                url="/login", status_code=302
            )

        # 인증 성공 → 다음 미들웨어/엔드포인트로 진행
        return await call_next(request)

    def _is_whitelisted(self, path: str) -> bool:
        """
        화이트리스트 경로 확인

        Args:
            path: 요청 경로

        Returns:
            화이트리스트 여부
        """
        # 정확한 경로 매칭
        if path in self.WHITELIST_PATHS:
            return True

        # 접두사 매칭
        for prefix in self.WHITELIST_PREFIXES:
            if path.startswith(prefix):
                return True

        return False

    def _is_html_request(self, request: Request) -> bool:
        """
        HTML 요청 확인

        Accept 헤더를 확인하여 HTML 요청인지 판단합니다.

        Args:
            request: 요청 객체

        Returns:
            HTML 요청 여부
        """
        accept = request.headers.get("accept", "")

        # Accept 헤더에 text/html이 포함되어 있으면 HTML 요청
        return "text/html" in accept.lower()

    async def _validate_session_in_db(
        self, user_id: int, is_admin: bool
    ) -> bool:
        """
        DB에서 세션 유효성 검증

        세션의 user_id와 is_admin 플래그가 DB와 일치하는지
        확인합니다.

        Args:
            user_id: 세션의 사용자 ID
            is_admin: 세션의 관리자 플래그

        Returns:
            세션 유효 여부

        Note:
            매 요청마다 DB 조회가 발생하므로 성능에 영향을 줄 수
            있습니다. 프로덕션 환경에서는 캐싱이나 Redis 세션을
            고려하세요.
        """
        try:
            async with async_session_maker() as session:
                # DB에서 사용자 조회
                result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                user = result.scalar_one_or_none()

                if not user:
                    logger.warning(
                        f"세션 검증 실패: "
                        f"user_id={user_id} DB에 없음"
                    )
                    return False

                # is_admin 플래그 일치 확인
                if user.is_admin != is_admin:
                    logger.warning(
                        f"세션 검증 실패: "
                        f"user_id={user_id} "
                        f"is_admin 불일치 "
                        f"(세션={is_admin}, DB={user.is_admin})"
                    )
                    return False

                return True

        except Exception as e:
            logger.error(
                f"세션 검증 중 오류: {str(e)}", exc_info=True
            )
            return False
