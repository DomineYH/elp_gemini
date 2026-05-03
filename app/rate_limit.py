"""
Rate limiter 인스턴스 (Issue #5)

`/auth/login/admin` brute-force 방어를 위한 IP 기반 rate limit.
순환 import 회피용으로 main.py 와 routers/auth.py 가 모두 이 모듈을 참조한다.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.RATE_LIMIT_ENABLED,
)
