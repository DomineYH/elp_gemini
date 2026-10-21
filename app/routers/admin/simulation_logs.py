"""
관리자 시뮬레이션 로그 라우터 (qna_logs 패턴)
세션 목록·상세(원본 프로필 포함) 조회
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_admin
from app.models.simulation_session import SimulationSession
from app.models.simulation_utterance import SimulationUtterance
from app.models.users import User
from app.services.simulation import session_service
from app.services.simulation.errors import SimulationError
from app.templating import templates

router = APIRouter(tags=["관리자-시뮬레이션로그"])


@router.get("/admin/api/simulation/sessions")
async def list_simulation_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """전체 사용자의 시뮬레이션 세션 목록 (최신순)"""
    total = await db.scalar(select(func.count(SimulationSession.id))) or 0
    counts = (
        select(
            SimulationUtterance.session_id,
            func.count(SimulationUtterance.id).label("n"),
        )
        .group_by(SimulationUtterance.session_id)
        .subquery()
    )
    rows = await db.execute(
        select(SimulationSession, User.username, counts.c.n)
        .join(User, User.id == SimulationSession.user_id)
        .outerjoin(counts, counts.c.session_id == SimulationSession.id)
        .order_by(
            SimulationSession.created_at.desc(), SimulationSession.id.desc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "sessions": [
            {
                "id": s.id,
                "user_id": s.user_id,
                "username": username,
                "created_at": s.created_at,
                "persona_count": s.persona_count,
                "status": s.status,
                "utterance_count": n or 0,
            }
            for s, username, n in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/admin/api/simulation/sessions/{sid}")
async def get_simulation_session(
    sid: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """세션 전체 상태 + 페르소나 원본 프로필 (관리자 전용)"""
    session = await db.get(SimulationSession, sid)
    if session is None:
        raise SimulationError("SESSION_NOT_FOUND").to_http()
    state = await session_service.load_state(db, session)
    raw = {
        p.id: p.raw_profile for p in await session_service._personas(db, sid)
    }
    for persona in state["personas"]:
        persona["raw_profile"] = raw[persona["id"]]
    return state


@router.get("/admin/simulation/logs", response_class=HTMLResponse)
async def simulation_logs_page(
    request: Request,
    current_admin: User = Depends(get_current_admin),
):
    """시뮬레이션 로그 페이지 렌더링"""
    return templates.TemplateResponse(
        "admin/admin_simulation_logs.html",
        {"request": request, "user": current_admin},
    )
