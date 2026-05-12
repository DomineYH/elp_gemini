"""
관리자 사용자 관리 라우터
학년별 통계, 세션 목록, 세션 상세 API
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.constants import USER_TYPES
from app.db import get_db
from app.dependencies import get_current_admin
from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import (
    ChatMessage,
    MessageRole,
)
from app.models.chat_sessions import ChatSession
from app.models.user_profiles import UserProfile
from app.models.users import User
from app.services.admin_deletion_service import AdminDeletionService
from app.services.auth_service import AuthService
from app.utils.admin_csrf import (
    ensure_admin_csrf_token,
    require_admin_csrf_token,
)
from app.utils.logging import log_auth_event, log_user_action

router = APIRouter(tags=["관리자-사용자관리"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)

PROFILE_ROLE_LABELS = {
    "teacher": "교사",
    "preservice_teacher": "예비교사",
}


def _role_str(role):
    """role 문자열 추출 (방어적)"""
    return role.value if hasattr(role, "value") \
        else str(role)


def _value_str(value: Any) -> str | None:
    """Enum/문자열 값을 JSON 친화 문자열로 변환한다."""
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _serialize_profile(profile: Any) -> dict[str, Any]:
    """프로필 객체를 관리자 화면/API 표시용으로 직렬화한다."""
    if profile is None:
        return {
            "role": None,
            "role_label": "-",
            "teacher_region": None,
            "teacher_career_years": None,
            "preservice_university_region": None,
            "preservice_grade": None,
            "summary": "-",
        }

    role = _value_str(getattr(profile, "role", None))
    role_label = PROFILE_ROLE_LABELS.get(role, role or "-")
    teacher_region = getattr(profile, "teacher_region", None)
    teacher_career_years = getattr(
        profile, "teacher_career_years", None
    )
    preservice_university_region = getattr(
        profile, "preservice_university_region", None
    )
    preservice_grade = getattr(profile, "preservice_grade", None)

    if role == "teacher":
        detail_parts = [
            teacher_region,
            (
                f"{teacher_career_years}년"
                if teacher_career_years is not None
                else None
            ),
        ]
    elif role == "preservice_teacher":
        detail_parts = [
            preservice_university_region,
            (
                f"{preservice_grade}학년"
                if preservice_grade is not None
                else None
            ),
        ]
    else:
        detail_parts = [
            teacher_region or preservice_university_region,
            (
                f"{teacher_career_years}년"
                if teacher_career_years is not None
                else None
            ),
            (
                f"{preservice_grade}학년"
                if preservice_grade is not None
                else None
            ),
        ]

    detail = " · ".join(
        str(part) for part in detail_parts if part not in (None, "")
    )
    summary = role_label if not detail else f"{role_label} · {detail}"

    return {
        "role": role,
        "role_label": role_label,
        "teacher_region": teacher_region,
        "teacher_career_years": teacher_career_years,
        "preservice_university_region": preservice_university_region,
        "preservice_grade": preservice_grade,
        "summary": summary,
    }


async def _load_profiles(
    db: AsyncSession,
    user_ids: set[int],
) -> dict[int, dict[str, Any]]:
    """사용자 프로필을 일괄 조회한다. 프로필 미구현/미마이그레이션은 무시."""
    if not user_ids:
        return {}

    try:
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id.in_(user_ids))
        )
    except Exception as exc:
        await db.rollback()
        logger.warning("사용자 프로필 조회 생략: %s", exc)
        return {}

    return {
        profile.user_id: _serialize_profile(profile)
        for profile in result.scalars().all()
    }


async def _get_profile_totals(db: AsyncSession) -> dict[str, int]:
    """등록 사용자/프로필 통계를 가져온다."""
    totals = {
        "regular_user_count": 0,
        "teacher_count": 0,
        "preservice_teacher_count": 0,
        "no_profile_count": 0,
    }

    result = await db.execute(
        select(func.count(User.id)).where(User.is_admin.is_(False))
    )
    totals["regular_user_count"] = result.scalar() or 0

    try:
        role_counts = await db.execute(
            select(
                UserProfile.role,
                func.count(UserProfile.user_id),
            )
            .join(User, User.id == UserProfile.user_id)
            .where(User.is_admin.is_(False))
            .group_by(UserProfile.role)
        )
    except Exception as exc:
        await db.rollback()
        logger.warning("사용자 프로필 통계 생략: %s", exc)
        totals["no_profile_count"] = totals["regular_user_count"]
        return totals

    counted = 0
    for role, count in role_counts:
        role_value = _value_str(role)
        count = count or 0
        counted += count
        if role_value == "teacher":
            totals["teacher_count"] = count
        elif role_value == "preservice_teacher":
            totals["preservice_teacher_count"] = count

    totals["no_profile_count"] = max(
        totals["regular_user_count"] - counted,
        0,
    )
    return totals


async def _count_sessions_by_user(
    db: AsyncSession,
    user_ids: set[int],
) -> dict[int, int]:
    if not user_ids:
        return {}
    rows = await db.execute(
        select(ChatSession.user_id, func.count(ChatSession.id))
        .where(ChatSession.user_id.in_(user_ids))
        .group_by(ChatSession.user_id)
    )
    return {user_id: count for user_id, count in rows}


async def _count_reports_by_user(
    db: AsyncSession,
    user_ids: set[int],
) -> dict[int, int]:
    if not user_ids:
        return {}
    rows = await db.execute(
        select(AnalysisReport.user_id, func.count(AnalysisReport.id))
        .where(AnalysisReport.user_id.in_(user_ids))
        .group_by(AnalysisReport.user_id)
    )
    return {user_id: count for user_id, count in rows}


async def _extract_new_password(request: Request) -> str:
    """JSON/form 요청에서 새 비밀번호를 추출한다."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="요청 본문이 올바른 JSON 형식이 아닙니다.",
            )
    else:
        payload = dict(await request.form())

    password = payload.get("new_password") or payload.get("password")
    if password is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="새 비밀번호를 입력해주세요.",
        )
    return str(password)


def _audit_password_change(
    current_admin: User,
    target_user_id: int,
    success: bool,
    reason: str | None = None,
) -> None:
    """관리자 비밀번호 변경 성공/실패를 감사 로그에 남긴다."""
    details: dict[str, Any] = {"target_user_id": target_user_id}
    if reason:
        details["reason"] = reason
    log_user_action(
        user_id=current_admin.id,
        action="admin_user_password_change",
        details=details,
        success=success,
    )


@router.get("/admin/api/users/stats")
async def get_user_stats(
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """레거시 세션 세그먼트별 사용자 통계 API."""
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
        profile_totals = await _get_profile_totals(db)
        logger.info(
            f"사용자 통계 조회: "
            f"admin={current_admin.username}")
        return {
            "stats": stats,
            "totals": totals,
            "profile_totals": profile_totals,
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
            .options(
                selectinload(ChatSession.messages),
                selectinload(ChatSession.user),
            )
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
                "user_email": (
                    user.email if user is not None else None
                ),
                "username": (
                    user.username if user is not None else None
                ),
                "nickname": (
                    user.nickname if user is not None else None
                ),
                "profile": profile,
                "profile_role": profile["role"],
                "profile_summary": profile["summary"],
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
                "can_change_password": (
                    not account.is_admin and bool(account.email)
                ),
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


@router.get("/admin/api/users/{user_id}/sessions")
async def get_user_sessions_for_admin(
    user_id: int,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자가 특정 사용자의 대화 세션 목록을 조회한다.

    사용자 측 `/api/qna/sessions`와 동일한 정렬/필드 셰입을 반환하되,
    소유권 검사 없이 관리자 권한으로 접근한다.
    """
    user_row = await db.execute(
        select(User.id).where(User.id == user_id)
    )
    if user_row.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다.",
        )

    stats_session = aliased(ChatSession)
    message_stats = (
        select(
            ChatMessage.session_id,
            func.count(ChatMessage.id).label("message_count"),
            func.max(ChatMessage.created_at).label("last_message_at"),
        )
        .join(stats_session, stats_session.id == ChatMessage.session_id)
        .where(stats_session.user_id == user_id)
        .group_by(ChatMessage.session_id)
        .subquery()
    )

    total_result = await db.execute(
        select(func.count(ChatSession.id)).where(
            ChatSession.user_id == user_id
        )
    )
    total_count = int(total_result.scalar_one() or 0)

    last_activity_at = func.coalesce(
        message_stats.c.last_message_at,
        ChatSession.updated_at,
    )

    result = await db.execute(
        select(
            ChatSession,
            func.coalesce(message_stats.c.message_count, 0).label("message_count"),
            message_stats.c.last_message_at,
        )
        .outerjoin(
            message_stats,
            ChatSession.id == message_stats.c.session_id,
        )
        .where(ChatSession.user_id == user_id)
        .order_by(last_activity_at.desc(), ChatSession.id.desc())
        .offset(offset)
        .limit(limit)
    )

    sessions = []
    for session, message_count, last_message_at in result.all():
        sessions.append({
            "session_id": session.id,
            "title": session.title,
            "user_type": session.user_type,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            "message_count": int(message_count or 0),
            "last_message_at": last_message_at.isoformat() if last_message_at else None,
        })

    logger.info(
        "관리자 사용자 세션 목록: admin=%s, target=%s, total=%s",
        current_admin.username, user_id, total_count,
    )
    return {
        "user_id": user_id,
        "sessions": sessions,
        "total_count": total_count,
        "returned_count": len(sessions),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(sessions) < total_count,
    }


@router.get("/admin/api/users/{user_id}/reports")
async def get_user_reports_for_admin(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자가 특정 사용자의 분석 보고서 목록을 조회한다.

    사용자 측 `/api/lessonplan/reports`와 동일한 정렬(생성일 desc)·필드를 반환한다.
    """
    user_row = await db.execute(
        select(User.id).where(User.id == user_id)
    )
    if user_row.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다.",
        )

    total_result = await db.execute(
        select(func.count(AnalysisReport.id)).where(
            AnalysisReport.user_id == user_id
        )
    )
    total_count = int(total_result.scalar_one() or 0)

    result = await db.execute(
        select(AnalysisReport)
        .where(AnalysisReport.user_id == user_id)
        .order_by(AnalysisReport.created_at.desc(), AnalysisReport.id.desc())
        .offset(offset)
        .limit(limit)
    )
    reports = [
        {
            "id": r.id,
            "report_filename": r.report_filename,
            "lessonplan_filename": r.lessonplan_filename,
            "lessonplan_original_name": getattr(r, "lessonplan_original_name", None),
            "latency_ms": r.latency_ms,
            "created_at": r.created_at.isoformat(),
        }
        for r in result.scalars().all()
    ]

    logger.info(
        "관리자 사용자 보고서 목록: admin=%s, target=%s, total=%s",
        current_admin.username, user_id, total_count,
    )
    return {
        "user_id": user_id,
        "reports": reports,
        "total_count": total_count,
        "returned_count": len(reports),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(reports) < total_count,
    }


@router.get("/admin/api/users/{user_id}")
async def get_user_profile_for_admin(
    user_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 화면 헤더용 사용자 식별/프로필/카운트 조회."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다.",
        )

    profile_map = await _load_profiles(db, {target.id})
    profile = profile_map.get(target.id, _serialize_profile(None))
    session_counts = await _count_sessions_by_user(db, {target.id})
    report_counts = await _count_reports_by_user(db, {target.id})

    return {
        "user_id": target.id,
        "username": target.username,
        "nickname": target.nickname,
        "email": target.email,
        "is_admin": target.is_admin,
        "created_at": (
            target.created_at.isoformat() if target.created_at else None
        ),
        "profile": profile,
        "session_count": session_counts.get(target.id, 0),
        "report_count": report_counts.get(target.id, 0),
    }


@router.get("/admin/api/reports/{report_id}")
async def get_admin_report_detail(
    report_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 전용 분석 보고서 상세 조회 (소유자 우회).

    `app.routers.lessonplan_analysis.get_analysis_report`와 동일한 응답
    스키마를 반환하되, `AnalysisReport.user_id == current_user.id` 검사를
    수행하지 않는다. 관리자 권한 검증은 `get_current_admin`이 담당한다.
    """
    result = await db.execute(
        select(AnalysisReport).where(AnalysisReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="보고서를 찾을 수 없습니다.",
        )

    report_path = Path(report.report_path)
    if not report_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="보고서 파일이 존재하지 않습니다.",
        )

    content = report_path.read_text(encoding="utf-8")
    logger.info(
        "관리자 보고서 조회: admin=%s, report_id=%s",
        current_admin.username,
        report_id,
    )
    return {
        "id": report.id,
        "lessonplan_filename": report.lessonplan_filename,
        "lessonplan_original_name": report.lessonplan_original_name,
        "report_filename": report.report_filename,
        "content": content,
        "latency_ms": report.latency_ms,
        "created_at": report.created_at.isoformat(),
    }


@router.get(
    "/admin/reports/view/{report_id}",
    response_class=HTMLResponse,
)
async def admin_report_viewer_page(
    request: Request,
    report_id: int,
    current_admin: User = Depends(get_current_admin),
):
    """관리자 분석 보고서 뷰어 페이지 (HTML shell).

    실제 보고서 존재 검증은 페이지 내 `fetch`가 호출하는
    `/admin/api/reports/{report_id}`에서 수행한다.
    """
    if report_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="보고서를 찾을 수 없습니다.",
        )
    return templates.TemplateResponse(
        "admin/admin_report_viewer.html",
        {
            "request": request,
            "user": current_admin,
            "report_id": report_id,
        },
    )


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

    require_admin_csrf_token(request)

    try:
        new_password = await _extract_new_password(request)
    except HTTPException as exc:
        _audit_password_change(
            current_admin,
            user_id,
            success=False,
            reason=str(exc.detail),
        )
        raise

    auth_service = AuthService(db)

    try:
        target_user = await auth_service.admin_set_user_password(
            user_id, new_password
        )
    except ValueError as exc:
        reason = str(exc)
        if "찾을 수" in reason:
            status_code = status.HTTP_404_NOT_FOUND
        elif "관리자 계정" in reason:
            status_code = status.HTTP_403_FORBIDDEN
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        _audit_password_change(
            current_admin,
            user_id,
            success=False,
            reason=reason,
        )
        raise HTTPException(status_code=status_code, detail=reason) from exc

    try:
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


@router.delete("/admin/api/users/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 전용 사용자 삭제 API.

    cascade: chat_sessions / chat_messages / analysis_reports / user_profiles.
    파일: 각 AnalysisReport의 report_path(.md) + lessonplan_filename(.pdf).
    """
    require_admin_csrf_token(request)

    service = AdminDeletionService(db)
    try:
        result = await service.delete_user(
            target_user_id=user_id,
            current_admin_id=current_admin.id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        log_user_action(
            user_id=current_admin.id,
            action="admin_user_delete",
            details={
                "target_user_id": user_id,
                "reason": str(exc),
            },
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    logger.info(
        "관리자 사용자 삭제: admin_id=%s, target_user_id=%s",
        current_admin.id,
        user_id,
    )
    return result


@router.delete("/admin/api/chat-sessions/{session_id}")
async def delete_chat_session(
    session_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 전용 단일 대화 세션 삭제 (messages cascade)."""
    require_admin_csrf_token(request)
    service = AdminDeletionService(db)
    try:
        result = await service.delete_chat_session(
            session_id=session_id,
            current_admin_id=current_admin.id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    logger.info(
        "관리자 대화 세션 삭제: admin_id=%s, session_id=%s",
        current_admin.id,
        session_id,
    )
    return result


@router.delete("/admin/api/reports/{report_id}")
async def delete_analysis_report(
    report_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 전용 단일 분석 보고서 삭제 (.md/.pdf 파일 포함)."""
    require_admin_csrf_token(request)
    service = AdminDeletionService(db)
    try:
        result = await service.delete_analysis_report(
            report_id=report_id,
            current_admin_id=current_admin.id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    logger.info(
        "관리자 분석 보고서 삭제: admin_id=%s, report_id=%s",
        current_admin.id,
        report_id,
    )
    return result


@router.get(
    "/admin/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    current_admin: User = Depends(get_current_admin),
):
    """사용자 관리 페이지 렌더링"""
    csrf_token = ensure_admin_csrf_token(request)
    return templates.TemplateResponse(
        "admin/admin_users.html",
        {
            "request": request,
            "user": current_admin,
            "csrf_token": csrf_token,
        })


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


@router.get(
    "/admin/users/{user_id}",
    response_class=HTMLResponse,
)
async def admin_user_detail_page(
    request: Request,
    user_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 사용자 상세 페이지(HTML 셸).

    실제 데이터는 페이지 JS가 `/admin/api/users/{user_id}` 계열을 호출한다.
    """
    if user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다.",
        )
    result = await db.execute(
        select(User.id).where(User.id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다.",
        )
    return templates.TemplateResponse(
        "admin/admin_user_detail.html",
        {
            "request": request,
            "user": current_admin,
            "target_user_id": user_id,
        },
    )
