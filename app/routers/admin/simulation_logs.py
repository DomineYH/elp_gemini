"""
관리자 시뮬레이션 로그 라우터 (qna_logs 패턴)
세션 목록·상세(원본 프로필 포함) 조회
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_admin
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.simulation_session import SimulationSession
from app.models.simulation_utterance import SimulationUtterance
from app.models.users import User
from app.services.simulation import session_service
from app.services.simulation.errors import SimulationError
from app.services.simulation.session_report import render_session_markdown
from app.templating import templates
from app.utils.admin_export_naming import build_simsession_basename
from app.utils.timestamps import utc_iso

router = APIRouter(tags=["관리자-시뮬레이션로그"])


@router.get("/admin/api/simulation/sessions")
async def list_simulation_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: int | None = Query(None),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """시뮬레이션 세션 목록 (최신순). user_id로 한 사용자만 (#188)"""
    filters = (
        [SimulationSession.user_id == user_id] if user_id is not None else []
    )
    total = (
        await db.scalar(
            select(func.count(SimulationSession.id)).where(*filters)
        )
        or 0
    )
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
        .where(*filters)
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
                "created_at": utc_iso(s.created_at),
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
    state["feedback"] = session.feedback_json
    return state


@router.get("/admin/api/simulation/sessions/{sid}/download")
async def download_simulation_session(
    sid: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """대화록 + 피드백 Markdown (#280)"""
    session = await db.get(SimulationSession, sid)
    if session is None:
        raise SimulationError("SESSION_NOT_FOUND").to_http()
    owner = await db.get(User, session.user_id)
    upload = await db.get(LessonPlanUpload, session.upload_id)
    lessonplan_name = upload.original_filename or upload.filename
    md = render_session_markdown(
        session,
        owner.username,
        lessonplan_name,
        await session_service._phases(db, sid),
        await session_service._personas(db, sid),
        await session_service._utterances(db, sid),
    )
    basename = build_simsession_basename(
        session.user_id, session.upload_id, lessonplan_name, sid
    )
    # 한글 이름은 latin-1 헤더에 못 넣으므로 RFC 5987 + ASCII 대체 이름
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="simulation_{sid}.md"; '
                f"filename*=UTF-8''{quote(basename + '.md')}"
            )
        },
    )


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
