"""
관리자 시뮬레이션 설정: 피드백 지침 버전 관리·미리보기 (#159)
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_admin
from app.models.users import User
from app.schemas.simulation_guidelines import GuidelineIn
from app.services.simulation import feedback, guidelines
from app.services.simulation.errors import SimulationError
from app.templating import templates
from app.utils.admin_csrf import (
    ensure_admin_csrf_token,
    require_admin_csrf_token,
)

router = APIRouter(tags=["관리자-시뮬레이션"])
API = "/admin/api/simulation/feedback-guidelines"


@router.get("/admin/simulation/settings", response_class=HTMLResponse)
async def simulation_settings_page(
    request: Request,
    current_admin: User = Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "admin/admin_simulation_settings.html",
        {
            "request": request,
            "user": current_admin,
            "csrf_token": ensure_admin_csrf_token(request),
        },
    )


@router.get(API)
async def get_guidelines(
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    history = [guidelines.to_out(row) for row in await guidelines.history(db)]
    return {
        "current": history[0] if history else None,
        "history": history,
        "aspects": {
            "fixed": guidelines.FIXED_ASPECTS,
            "optional": [
                {"key": k, "label": v}
                for k, v in guidelines.OPTIONAL_ASPECTS.items()
            ],
        },
        "criteria": await guidelines.active_criteria(db),
        "base_prompt": guidelines.base_prompt(),
    }


@router.post(API, status_code=201)
async def save_guideline(
    request: Request,
    body: GuidelineIn,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    require_admin_csrf_token(request)
    try:
        row = await guidelines.save(db, body.model_dump(), current_admin.id)
    except SimulationError as e:
        raise e.to_http() from e
    return guidelines.to_out(row)


@router.post(f"{API}/preview")
async def preview_guideline(
    request: Request,
    body: GuidelineIn,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 본인의 최근 종료 세션으로 1회 생성. 아무것도 저장하지 않는다."""
    require_admin_csrf_token(request)
    try:
        session = await guidelines.latest_finished_session(db, current_admin.id)
        if session is None:
            raise SimulationError("NO_SAMPLE_SESSION")
        system = await guidelines.system_prompt(db, body)
        result = await feedback.call_model(db, session, system)
    except SimulationError as e:
        raise e.to_http() from e
    return {
        "feedback": result.parsed.model_dump(),
        "model_name": result.model,
        "latency_ms": result.latency_ms,
    }
