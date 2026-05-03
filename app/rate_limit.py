"""
Rate limiter 인스턴스 (Issue #5)

`/auth/login/admin` brute-force 방어를 위한 IP 기반 rate limit.
순환 import 회피용으로 main.py 와 routers/auth.py 가 모두 이 모듈을 참조한다.
"""
from fastapi import HTTPException, status
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.RATE_LIMIT_ENABLED,
)

# admin_id 기반 rate limit (Issue #5: IP + admin_id 이중 방어)
_admin_id_limit_item = parse(settings.ADMIN_LOGIN_RATE_LIMIT_PER_ID)


def check_admin_id_rate_limit(admin_id: str) -> None:
    """admin_id 기반 rate limit 검사. 초과 시 429 발생.

    IP 기반과 독립적으로 동일 admin_id 에 대해 시간당 요청 수를 제한한다.
    공격자가 IP 를 순환시켜도 특정 계정에 대한 brute-force 를 방지한다.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return
    key = f"admin:{admin_id.lower()}"
    allowed = limiter._limiter.hit(_admin_id_limit_item, key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
        )
