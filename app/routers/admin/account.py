"""
관리자 본인 계정: 비밀번호 변경 (#264)
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_admin
from app.models.users import User
from app.services.auth_service import AuthService
from app.templating import templates
from app.utils.admin_csrf import (
    ensure_admin_csrf_token,
    require_admin_csrf_token,
)
from app.utils.logging import log_user_action

router = APIRouter(tags=["관리자-계정"])


@router.get("/admin/account", response_class=HTMLResponse)
async def account_page(
    request: Request,
    current_admin: User = Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "admin/admin_account.html",
        {
            "request": request,
            "user": current_admin,
            "csrf_token": ensure_admin_csrf_token(request),
        },
    )


def _fail(admin: User, reason: str) -> HTTPException:
    # 감사 로그에는 사유만 남기고 비밀번호는 남기지 않는다
    log_user_action(
        user_id=admin.id,
        action="admin_self_password_change",
        details={"reason": reason},
        success=False,
    )
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)


@router.post("/admin/api/account/password")
async def change_own_password(
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    require_admin_csrf_token(request)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise _fail(current_admin, "요청 본문이 올바른 JSON 형식이 아닙니다.")

    new_password = str(body.get("new_password") or "")
    if new_password != str(body.get("confirm_password") or ""):
        raise _fail(current_admin, "새 비밀번호와 확인 값이 일치하지 않습니다.")
    try:
        new_version = await AuthService(db).change_own_password(
            current_admin,
            str(body.get("current_password") or ""),
            new_password,
        )
    except ValueError as exc:
        raise _fail(current_admin, str(exc)) from None

    # 요청한 본인 세션은 유지, 다른 세션은 session_version 불일치로 401
    request.session["session_version"] = new_version
    log_user_action(
        user_id=current_admin.id, action="admin_self_password_change"
    )
    return {"message": "비밀번호가 변경되었습니다."}
