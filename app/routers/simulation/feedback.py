"""
수업 시뮬레이션 대화록·피드백 라우터 (#156)
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.models.users import User
from app.services.simulation import feedback, session_service
from app.services.simulation.errors import SimulationError
from app.templating import templates

router = APIRouter(tags=["수업 시뮬레이션"])


async def _page(template, sid, request, current_user, db):
    try:
        session = await session_service.get_owned_session(
            db, sid, current_user.id
        )
    except SimulationError:
        raise HTTPException(
            status_code=404, detail="시뮬레이션 세션을 찾을 수 없습니다."
        )
    return templates.TemplateResponse(
        template,
        {
            "request": request,
            "user": current_user,
            "sid": session.id,
            "disclaimer": feedback.DISCLAIMER,
            "section_note": feedback.SECTION_NOTE,
        },
    )


@router.get(
    "/simulation/sessions/{sid}/transcript", response_class=HTMLResponse
)
async def transcript_page(
    sid: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _page(
        "user/simulation_transcript.html", sid, request, current_user, db
    )


@router.get("/simulation/sessions/{sid}/feedback", response_class=HTMLResponse)
async def feedback_page(
    sid: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _page(
        "user/simulation_feedback.html", sid, request, current_user, db
    )


@router.post("/api/simulation/sessions/{sid}/feedback")
async def create_feedback(
    sid: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await session_service.get_owned_session(
            db, sid, current_user.id
        )
        return await feedback.generate(db, session)
    except SimulationError as e:
        raise e.to_http() from e


async def _feedback_session(db, sid, user_id):
    session = await session_service.get_owned_session(db, sid, user_id)
    if session.feedback_json is None:
        raise SimulationError("NO_FEEDBACK")
    return session


@router.get("/api/simulation/sessions/{sid}/feedback")
async def get_feedback(
    sid: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await _feedback_session(db, sid, current_user.id)
    except SimulationError as e:
        raise e.to_http() from e
    return session.feedback_json


@router.get("/api/simulation/sessions/{sid}/feedback/download")
async def download_feedback(
    sid: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await _feedback_session(db, sid, current_user.id)
        # 경로는 DB 행에서만 온다
        path = Path(session.feedback_report_path or "")
        if not path.is_file():
            raise SimulationError("NO_FEEDBACK")
    except SimulationError as e:
        raise e.to_http() from e
    return FileResponse(
        path,
        media_type="text/markdown; charset=utf-8",
        filename=f"simulation_{sid}_feedback.md",
    )
