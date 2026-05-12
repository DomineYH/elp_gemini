"""관리자 상태 변경 요청용 CSRF 토큰 헬퍼.

세션에 토큰을 저장하고 헤더로 받은 토큰과 상수시간 비교한다.
"""
import secrets

from fastapi import HTTPException, Request, status

ADMIN_CSRF_SESSION_KEY = "admin_csrf_token"
ADMIN_CSRF_HEADER = "x-csrf-token"


def ensure_admin_csrf_token(request: Request) -> str:
    """세션에 CSRF 토큰을 생성/보관하고 토큰 문자열을 반환한다."""
    token = request.session.get(ADMIN_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[ADMIN_CSRF_SESSION_KEY] = token
    return str(token)


def require_admin_csrf_token(request: Request) -> None:
    """세션 토큰과 요청 헤더를 상수시간 비교한다. 불일치 시 403."""
    expected = request.session.get(ADMIN_CSRF_SESSION_KEY)
    provided = request.headers.get(ADMIN_CSRF_HEADER)
    if (
        not expected
        or not provided
        or not secrets.compare_digest(str(expected), str(provided))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF 토큰이 유효하지 않습니다.",
        )
