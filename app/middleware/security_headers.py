"""
보안 응답 헤더 미들웨어 (#268)

모든 HTTP 응답에 기본 보안 헤더를 붙입니다 (이미 있으면 유지).
HSTS 는 TLS 를 종료하는 리버스 프록시에서 설정합니다 (README 참고).
CSP 는 인라인 스크립트 제거 전까지 Report-Only 로만 보냅니다.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# marked 는 cdn.jsdelivr.net 에서 로드, pdf.js 워커는 /static/js/lib (blob 폴백)
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'self'; "
    "object-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy-Report-Only": CONTENT_SECURITY_POLICY,
}


class SecurityHeadersMiddleware:
    """http 응답 시작 메시지에 SECURITY_HEADERS 를 추가하는 ASGI 미들웨어"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
