"""
평가 기준 활성화 라우터
관리자 전용 기준 문서 활성화/비활성화
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.users import User
from app.models.criteria import (
    CriteriaActivateResponse,
    CriteriaDetailResponse,
)
from app.repositories.criteria_repository import (
    CriteriaRepository,
)
from app.services.criteria_audit_service import (
    CriteriaAuditService,
)
from app.routers.auth import get_current_admin

router = APIRouter(tags=["admin", "criteria"])
logger = logging.getLogger(__name__)


@router.post("/{criteria_id}/activate")
async def activate_criteria(
    criteria_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """평가 기준 문서 활성화"""
    try:
        repo = CriteriaRepository(db)

        # 기존 활성 문서 조회 (감사 로그용)
        previous_active = await repo.get_active()
        previous_id = (
            previous_active.id
            if previous_active
            else None
        )

        # 활성화 (트랜잭션)
        document = await repo.activate_criteria(
            criteria_id=criteria_id, admin_id=current_user.id
        )

        # 감사 로그 기록
        audit_service = CriteriaAuditService(db)
        await audit_service.log_activate(
            criteria_id=document.id,
            actor_id=current_user.id,
            title=document.title,
            previous_active_id=previous_id,
        )

        await db.commit()
        await db.refresh(document)

        # 캐시 재로드
        from app.services.criteria_context_provider import (
            criteria_context_provider,
        )

        await criteria_context_provider.reload_active()

        logger.info(
            f"활성화 완료: id={document.id}, "
            f"admin={current_user.id}"
        )

        return CriteriaActivateResponse(
            criteria_id=document.id,
            title=document.title,
            activated_at=document.activated_at,
            activated_by=document.activated_by,
        )

    except ValueError as e:
        logger.warning(f"활성화 실패 - {e}")
        raise HTTPException(status_code=404, detail=str(e))

    except Exception as e:
        logger.error(f"활성화 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="활성화 중 오류 발생"
        )


@router.post("/deactivate")
async def deactivate_criteria(
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """현재 활성 기준 문서 비활성화"""
    try:
        repo = CriteriaRepository(db)

        # 현재 활성 문서 조회 (감사 로그용)
        active_doc = await repo.get_active()
        if not active_doc:
            raise HTTPException(
                status_code=404, detail="활성 기준 문서가 없습니다"
            )

        # 비활성화 (트랜잭션)
        criteria_id = await repo.deactivate_all()

        # 감사 로그 기록
        audit_service = CriteriaAuditService(db)
        await audit_service.log_deactivate(
            criteria_id=active_doc.id,
            actor_id=current_user.id,
            title=active_doc.title,
        )

        await db.commit()

        # 캐시 재로드
        from app.services.criteria_context_provider import (
            criteria_context_provider,
        )

        await criteria_context_provider.reload_active()

        logger.info(
            f"비활성화 완료: id={criteria_id}, "
            f"admin={current_user.id}"
        )

        return {
            "message": "비활성화되었습니다",
            "criteria_id": criteria_id,
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"비활성화 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="비활성화 중 오류 발생"
        )


@router.get("/active", response_model=CriteriaDetailResponse)
async def get_active_criteria(
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """현재 활성 기준 문서 조회"""
    try:
        repo = CriteriaRepository(db)
        document = await repo.get_active()

        if not document:
            raise HTTPException(
                status_code=404, detail="활성 기준 문서가 없습니다"
            )

        return CriteriaDetailResponse.model_validate(document)

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"활성 기준 조회 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="문서를 불러올 수 없습니다"
        )
