"""
관리자 사용자 관리 라우터
학년별 통계, 세션 목록, 세션 상세 API
"""
from fastapi import (
    APIRouter, Depends, HTTPException, Query, Request,
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
from sqlalchemy.orm import selectinload
from datetime import datetime
import logging

from app.constants import USER_TYPES
from app.db import get_db
from app.dependencies import get_current_admin
from app.models.users import User
from app.models.chat_sessions import ChatSession
from app.models.chat_messages import (
    ChatMessage, MessageRole,
)
from app.models.analysis_reports import AnalysisReport

router = APIRouter(tags=["관리자-사용자관리"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


def _role_str(role):
    """role 문자열 추출 (방어적)"""
    return role.value if hasattr(role, "value") \
        else str(role)


@router.get("/admin/api/users/stats")
async def get_user_stats(
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """학년별 사용자 통계 API"""
    try:
        today = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0)
        ut_in = ChatSession.user_type.in_(USER_TYPES)
        # 세션+오늘 세션 (1 쿼리)
        sess_q = (
            select(
                ChatSession.user_type,
                func.count().label("sc"),
                func.count(case(
                    (ChatSession.created_at >= today,
                     1),
                )).label("tc"),
            ).where(ut_in)
            .group_by(ChatSession.user_type))
        sess = {
            r.user_type: (r.sc, r.tc)
            for r in await db.execute(sess_q)}
        # QnA 수 (1 쿼리)
        qna_q = (
            select(
                ChatSession.user_type,
                func.count().label("qc"),
            ).select_from(ChatMessage)
            .join(ChatSession).where(
                ChatMessage.role == MessageRole.USER,
                ut_in,
            ).group_by(ChatSession.user_type))
        qna = {
            r.user_type: r.qc
            for r in await db.execute(qna_q)}
        # 보고서 수 - distinct로 cross product 방지
        rpt_q = (
            select(
                ChatSession.user_type,
                func.count(func.distinct(
                    AnalysisReport.id
                )).label("rc"),
            ).select_from(AnalysisReport)
            .join(User).join(
                ChatSession,
                ChatSession.user_id == User.id,
            ).where(ut_in)
            .group_by(ChatSession.user_type))
        rpt = {
            r.user_type: r.rc
            for r in await db.execute(rpt_q)}
        stats = []
        totals = dict(
            session_count=0, qna_count=0,
            report_count=0, today_count=0)
        for ut in USER_TYPES:
            sc, tc = sess.get(ut, (0, 0))
            entry = dict(
                user_type=ut, session_count=sc,
                qna_count=qna.get(ut, 0),
                report_count=rpt.get(ut, 0),
                today_count=tc)
            stats.append(entry)
            for k in totals:
                totals[k] += entry[k]
        logger.info(
            f"사용자 통계 조회: "
            f"admin={current_admin.username}")
        return {"stats": stats, "totals": totals}
    except Exception as e:
        logger.error(
            f"사용자 통계 조회 실패: {e}",
            exc_info=True)
        raise


@router.get("/admin/api/users/sessions")
async def get_user_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_type: str = Query(None),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """세션 목록 API (페이징)"""
    try:
        query = (
            select(ChatSession)
            .options(
                selectinload(ChatSession.messages))
            .order_by(ChatSession.created_at.desc()))
        cnt_q = select(func.count()).select_from(
            ChatSession)
        if user_type:
            flt = ChatSession.user_type == user_type
            query = query.where(flt)
            cnt_q = cnt_q.where(flt)
        total_r = await db.execute(cnt_q)
        total = total_r.scalar() or 0
        offset = (page - 1) * page_size
        result = await db.execute(
            query.offset(offset).limit(page_size))
        sessions = result.scalars().all()
        # 보고서 수 일괄 조회
        uids = {s.user_id for s in sessions}
        rpt_map = {}
        if uids:
            rc_q = (
                select(
                    AnalysisReport.user_id,
                    func.count().label("cnt"),
                ).where(
                    AnalysisReport.user_id.in_(uids)
                ).group_by(AnalysisReport.user_id))
            for row in await db.execute(rc_q):
                rpt_map[row.user_id] = row.cnt
        sessions_data = []
        for s in sessions:
            msgs = sorted(
                s.messages,
                key=lambda m: m.created_at)
            qna_c = sum(
                1 for m in msgs
                if m.role == MessageRole.USER)
            last = msgs[-1] if msgs else None
            last_at = (
                last.created_at.isoformat() if last
                else s.created_at.isoformat())
            sessions_data.append({
                "session_id": s.id,
                "user_type": s.user_type,
                "title": s.title,
                "created_at": (
                    s.created_at.isoformat()),
                "qna_count": qna_c,
                "message_count": len(msgs),
                "report_count": rpt_map.get(
                    s.user_id, 0),
                "last_activity": last_at,
                "status": (
                    "active" if msgs else "empty"),
            })
        logger.info(
            f"세션 목록: "
            f"admin={current_admin.username}"
            f", page={page}, total={total}")
        return {
            "sessions": sessions_data,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(
            f"세션 목록 조회 실패: {e}",
            exc_info=True)
        raise


@router.get(
    "/admin/api/users/session/{session_id}")
async def get_session_detail(
    session_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """세션 상세 API (메시지 + 보고서)"""
    try:
        query = (
            select(ChatSession)
            .options(
                selectinload(ChatSession.messages))
            .where(ChatSession.id == session_id))
        result = await db.execute(query)
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(
                status_code=404,
                detail="세션을 찾을 수 없습니다.")
        msgs = sorted(
            session.messages,
            key=lambda m: m.created_at)
        messages_data = [
            {
                "id": m.id,
                "role": _role_str(m.role),
                "content": m.content,
                "model_name": m.model_name,
                "citations": m.citations,
                "created_at": (
                    m.created_at.isoformat()),
            }
            for m in msgs
        ]
        rpt_q = (
            select(AnalysisReport)
            .where(
                AnalysisReport.user_id
                == session.user_id)
            .order_by(
                AnalysisReport.created_at.desc()))
        rpt_r = await db.execute(rpt_q)
        reports_data = [
            {
                "id": r.id,
                "filename": r.report_filename,
                "report_path": r.report_path,
                "latency_ms": r.latency_ms,
                "created_at": (
                    r.created_at.isoformat()),
            }
            for r in rpt_r.scalars().all()
        ]
        logger.info(
            f"세션 상세: session_id={session_id}")
        return {
            "session_id": session.id,
            "user_type": session.user_type,
            "title": session.title,
            "messages": messages_data,
            "reports": reports_data,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"세션 상세 조회 실패: {e}",
            exc_info=True)
        raise


@router.get(
    "/admin/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    current_admin: User = Depends(get_current_admin),
):
    """사용자 관리 페이지 렌더링"""
    return templates.TemplateResponse(
        "admin/admin_users.html",
        {"request": request, "user": current_admin})


@router.get(
    "/admin/users/session/{session_id}",
    response_class=HTMLResponse)
async def user_session_detail_page(
    request: Request,
    session_id: int,
    current_admin: User = Depends(get_current_admin),
):
    """세션 상세 페이지 렌더링"""
    return templates.TemplateResponse(
        "admin/admin_user_session_detail.html",
        {"request": request,
         "user": current_admin,
         "session_id": session_id})
