"""
관리자 사용자 관리 라우터
학년별 통계, 세션 목록, 세션 상세 API
"""
from fastapi import (
    APIRouter, Depends, Form, HTTPException, Query, Request,
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, or_
from sqlalchemy.orm import selectinload
from datetime import datetime
from typing import Any
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
from app.services.auth_service import AuthService
from app.utils.logging import log_user_action

router = APIRouter(tags=["관리자-사용자관리"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)

PASSWORD_MIN_LENGTH = 8
PROFILE_ROLE_LABELS = {
    "teacher": "교사",
    "preservice_teacher": "예비교사",
}


def _role_str(role):
    """role 문자열 추출 (방어적)"""
    return role.value if hasattr(role, "value") \
        else str(role)


PROFILE_ROLE_LABELS = {
    "teacher": "교사",
    "preservice_teacher": "예비교사",
}


def _user_profile(user: User):
    """User.profile 관계가 아직 없는 병렬 작업 상태도 허용."""
    return getattr(user, "profile", None)


def _profile_role_label(profile) -> str:
    if not profile:
        return "레거시"
    return PROFILE_ROLE_LABELS.get(profile.role, profile.role)


def _profile_region(profile) -> str | None:
    if not profile:
        return None
    if profile.role == "teacher":
        return profile.teacher_region
    if profile.role == "preservice_teacher":
        return profile.preservice_university_region
    return None


def _profile_detail(profile) -> str | None:
    if not profile:
        return None
    if profile.role == "teacher":
        years = profile.teacher_career_years
        return f"{years}년" if years is not None else None
    if profile.role == "preservice_teacher":
        grade = profile.preservice_grade
        return f"{grade}학년" if grade is not None else None
    return None


def _user_load_options():
    """관계가 통합된 경우 프로필까지 eager load."""
    user_loader = selectinload(ChatSession.user)
    options = [selectinload(ChatSession.messages), user_loader]
    if hasattr(User, "profile"):
        options.append(user_loader.selectinload(User.profile))
    return options


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
        profile_stats = []
        if hasattr(User, "profile"):
            users_result = await db.execute(
                select(User).options(selectinload(User.profile))
                .where(User.is_admin.is_(False))
            )
            profile_counts = {}
            for user in users_result.scalars().all():
                profile = _user_profile(user)
                key = (
                    _profile_role_label(profile),
                    _profile_region(profile) or "-",
                    _profile_detail(profile) or "-",
                )
                profile_counts[key] = profile_counts.get(key, 0) + 1
            profile_stats = [
                {
                    "role": role,
                    "region": region,
                    "detail": detail,
                    "user_count": count,
                }
                for (role, region, detail), count
                in sorted(profile_counts.items())
            ]
        logger.info(
            f"사용자 통계 조회: "
            f"admin={current_admin.username}")
        return {
            "stats": stats,
            "totals": totals,
            "profile_stats": profile_stats,
        }
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
            .options(*_user_load_options())
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
        profile_map = await _load_profiles(db, uids)
        sessions_data = []
        for s in sessions:
            user = s.user
            profile = _user_profile(user) if user else None
            msgs = sorted(
                s.messages,
                key=lambda m: m.created_at)
            qna_c = sum(
                1 for m in msgs
                if m.role == MessageRole.USER)
            last = msgs[-1] if msgs else None
            user = getattr(s, "user", None)
            profile = profile_map.get(
                s.user_id,
                _serialize_profile(None),
            )
            last_at = (
                last.created_at.isoformat() if last
                else s.created_at.isoformat())
            sessions_data.append({
                "session_id": s.id,
                "user_id": s.user_id,
                "email": user.email if user else None,
                "user_type": s.user_type,
                "profile_role": _profile_role_label(profile),
                "profile_region": _profile_region(profile),
                "profile_detail": _profile_detail(profile),
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


@router.get("/admin/api/users/accounts")
async def get_user_accounts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None),
    include_admins: bool = Query(False),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """일반 사용자 계정 목록 API.

    이메일+비밀번호 전환 이후 관리자는 세션 유무와 무관하게
    등록 사용자를 확인하고 비밀번호 변경 UI에 접근할 수 있어야 한다.
    """
    try:
        filters = []
        if not include_admins:
            filters.append(User.is_admin.is_(False))

        if q:
            term = f"%{q.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(User.email).like(term),
                    func.lower(User.username).like(term),
                    func.lower(User.nickname).like(term),
                )
            )

        query = select(User).order_by(
            User.created_at.desc(),
            User.id.desc(),
        )
        cnt_q = select(func.count(User.id))
        for flt in filters:
            query = query.where(flt)
            cnt_q = cnt_q.where(flt)

        total_r = await db.execute(cnt_q)
        total = total_r.scalar() or 0
        offset = (page - 1) * page_size
        result = await db.execute(
            query.offset(offset).limit(page_size)
        )
        users = result.scalars().all()

        user_ids = {user.id for user in users}
        session_counts = await _count_sessions_by_user(db, user_ids)
        report_counts = await _count_reports_by_user(db, user_ids)
        profile_map = await _load_profiles(db, user_ids)

        accounts = []
        for account in users:
            profile = profile_map.get(
                account.id,
                _serialize_profile(None),
            )
            accounts.append({
                "user_id": account.id,
                "username": account.username,
                "nickname": account.nickname,
                "email": account.email,
                "is_admin": account.is_admin,
                "created_at": (
                    account.created_at.isoformat()
                    if account.created_at
                    else None
                ),
                "profile": profile,
                "profile_role": profile["role"],
                "profile_summary": profile["summary"],
                "session_count": session_counts.get(account.id, 0),
                "report_count": report_counts.get(account.id, 0),
                "can_change_password": not account.is_admin,
            })

        logger.info(
            f"사용자 계정 목록: "
            f"admin={current_admin.username}, total={total}"
        )
        return {
            "accounts": accounts,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(
            f"사용자 계정 목록 조회 실패: {e}",
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


@router.post("/admin/api/users/{user_id}/password")
async def change_regular_user_password(
    user_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 전용 일반 사용자 비밀번호 변경 API."""
    if not current_admin.is_admin:
        log_auth_event(
            "permission_denied",
            user_id=current_admin.id,
            username=current_admin.username,
            success=False,
            reason="Admin permission required",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다.",
        )

    try:
        new_password = await _extract_new_password(request)
        _validate_new_password(new_password)
    except HTTPException as exc:
        _audit_password_change(
            current_admin,
            user_id,
            success=False,
            reason=str(exc.detail),
        )
        raise

    try:
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        target_user = result.scalar_one_or_none()
        if target_user is None:
            _audit_password_change(
                current_admin,
                user_id,
                success=False,
                reason="target_not_found",
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="사용자를 찾을 수 없습니다.",
            )

        if target_user.is_admin:
            _audit_password_change(
                current_admin,
                user_id,
                success=False,
                reason="admin_target_rejected",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="관리자 계정 비밀번호는 이 화면에서 변경할 수 없습니다.",
            )

        target_user.hashed_password = AuthService.hash_password(
            new_password
        )
        target_user.failed_login_count = 0
        target_user.locked_until = None
        target_user.last_failed_login_at = None
        await db.commit()
        await db.refresh(target_user)

        _audit_password_change(
            current_admin,
            target_user.id,
            success=True,
        )
        log_auth_event(
            "admin_password_change",
            user_id=target_user.id,
            username=target_user.username,
            success=True,
        )
        logger.info(
            "관리자 비밀번호 변경 성공: "
            "admin_id=%s, target_user_id=%s",
            current_admin.id,
            target_user.id,
        )
        return {
            "ok": True,
            "user_id": target_user.id,
            "message": "비밀번호가 변경되었습니다.",
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        _audit_password_change(
            current_admin,
            user_id,
            success=False,
            reason="internal_error",
        )
        logger.error(
            "관리자 비밀번호 변경 실패: "
            "admin_id=%s, target_user_id=%s, error=%s",
            current_admin.id,
            user_id,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="비밀번호 변경 중 오류가 발생했습니다.",
        )


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
