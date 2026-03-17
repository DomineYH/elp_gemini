"""
관리자 초대 코드 관리 라우터
"""
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.constants import USER_TYPES
from app.db import get_db
from app.dependencies import get_current_admin
from app.models.users import User
from app.services.invite_code_service import (
    InviteCodeService,
    CodeNotFoundError,
    CodeAlreadyActiveError,
    CodeInUseError,
)
from app.schemas.invite_codes import (
    InviteCodeCreate,
    InviteCodeResponse,
)

router = APIRouter(tags=["관리자-코드관리"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


@router.post("/admin/api/codes/generate")
async def generate_codes(
    body: InviteCodeCreate,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """코드 일괄 생성"""
    if body.user_type not in USER_TYPES:
        raise HTTPException(400, "유효하지 않은 사용자 유형")

    service = InviteCodeService(db)
    codes = await service.generate_codes(
        body.user_type, body.count, current_admin.id
    )
    return {
        "codes": [
            InviteCodeResponse.from_model(c) for c in codes
        ],
        "count": len(codes),
    }


@router.get("/admin/api/codes")
async def get_codes(
    user_type: str = Query(None),
    status: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """코드 목록 조회"""
    service = InviteCodeService(db)
    codes, total = await service.get_codes(
        user_type, status, page, page_size
    )
    return {
        "codes": [
            InviteCodeResponse.from_model(c) for c in codes
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/admin/api/codes/{code_id}/deactivate")
async def deactivate_code(
    code_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """코드 비활성화"""
    service = InviteCodeService(db)
    try:
        code = await service.deactivate_code(code_id)
        return {
            "message": "코드가 비활성화되었습니다.",
            "code_id": code.id,
        }
    except CodeNotFoundError as e:
        raise HTTPException(404, str(e))


@router.patch("/admin/api/codes/{code_id}/activate")
async def activate_code(
    code_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """비활성화된 코드 활성화"""
    service = InviteCodeService(db)
    try:
        code = await service.activate_code(code_id)
        return {
            "message": "코드가 활성화되었습니다.",
            "code_id": code.id,
        }
    except CodeNotFoundError as e:
        raise HTTPException(404, str(e))
    except CodeAlreadyActiveError as e:
        raise HTTPException(400, str(e))


@router.delete("/admin/api/codes/{code_id}")
async def delete_code(
    code_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """코드 영구 삭제 (미사용만)"""
    service = InviteCodeService(db)
    try:
        await service.delete_code(code_id)
        return {
            "message": "코드가 삭제되었습니다.",
            "code_id": code_id,
        }
    except CodeNotFoundError as e:
        raise HTTPException(404, str(e))
    except CodeInUseError as e:
        raise HTTPException(400, str(e))


@router.get("/admin/api/codes/stats")
async def get_code_stats(
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """코드 통계"""
    service = InviteCodeService(db)
    stats = await service.get_stats()
    return {"stats": stats}


@router.get("/admin/api/codes/export")
async def export_codes(
    user_type: str = Query(None),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """코드 목록 텍스트 내보내기"""
    service = InviteCodeService(db)
    codes, _ = await service.get_codes(
        user_type, "unused", 1, 1000
    )
    lines = [f"{c.code}\t{c.user_type}" for c in codes]
    text = "\n".join(lines)
    return PlainTextResponse(
        text,
        headers={
            "Content-Disposition": (
                "attachment; filename=invite_codes.txt"
            )
        },
    )


@router.get("/admin/codes", response_class=HTMLResponse)
async def codes_page(
    request: Request,
    current_admin: User = Depends(get_current_admin),
):
    """코드 관리 페이지 렌더링"""
    return templates.TemplateResponse(
        "admin/admin_codes.html",
        {"request": request, "user": current_admin},
    )
