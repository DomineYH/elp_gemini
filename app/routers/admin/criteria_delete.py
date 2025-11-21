"""
평가 기준 삭제 라우터
관리자 전용 기준 문서 삭제
"""
import os
import asyncio
import logging
from pathlib import Path
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.users import User
from app.repositories.criteria_repository import (
    CriteriaRepository,
)
from app.services.criteria_audit_service import (
    CriteriaAuditService,
)
from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService,
)
from app.routers.auth import get_current_admin

router = APIRouter(tags=["admin", "criteria"])
logger = logging.getLogger(__name__)


# ===== 응답 스키마 =====


class CriteriaDeleteResponse(BaseModel):
    """평가 기준 삭제 응답 스키마"""

    success: bool
    criteria_id: int
    title: str
    message: str


class CriteriaDeleteAllResponse(BaseModel):
    """평가 기준 전체 삭제 응답 스키마"""

    success: bool
    deleted_count: int
    message: str


# ===== 엔드포인트 =====


@router.delete("/{criteria_id}", response_model=CriteriaDeleteResponse)
async def delete_criteria(
    criteria_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    평가 기준 문서 삭제 (개별)

    Args:
        criteria_id: 삭제할 기준 문서 ID
        current_user: 현재 관리자 사용자
        db: 데이터베이스 세션

    Returns:
        삭제 결과

    Raises:
        HTTPException: 문서를 찾을 수 없거나 삭제 실패 시
    """
    try:
        repo = CriteriaRepository(db)

        # 1. 문서 조회 (삭제 전 정보 획득)
        document = await repo.get_by_id(criteria_id)

        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"평가 기준 문서를 찾을 수 없습니다 (ID: {criteria_id})",
            )

        # 2. Vector Store 삭제 (스토어 삭제 시 내부 문서도 자동 삭제)
        embedding_service = CriteriaEmbeddingService()

        if document.vector_store_id:
            logger.info(
                f"스토어 삭제 시작: "
                f"store_id={document.vector_store_id}"
            )
            vector_deleted = await embedding_service.delete_store(
                document.vector_store_id,
                ignore_errors=False,
            )

            if not vector_deleted:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Vector Store 삭제 실패: "
                        f"{document.vector_store_id}. "
                        f"삭제 작업이 중단되었습니다."
                    ),
                )
            logger.info(
                f"스토어 삭제 완료: "
                f"store_id={document.vector_store_id}"
            )

        # 3. 삭제 전 준비 (외래키 제약 조건 처리)
        from sqlalchemy import delete
        from app.models.criteria import ActiveCriteria, CriteriaAuditLog

        # 3-1. Active Criteria 삭제
        await db.execute(
            delete(ActiveCriteria).where(
                ActiveCriteria.criteria_document_id == criteria_id
            )
        )

        # 3-2. 기존 Audit 로그 삭제 (외래키 제약 조건)
        await db.execute(
            delete(CriteriaAuditLog).where(
                CriteriaAuditLog.criteria_document_id == criteria_id
            )
        )

        # 4. 문서 삭제 (Local DB)
        deleted_doc = await repo.delete_by_id(criteria_id)

        # 5. 파일 삭제
        file_path = Path(document.file_path)
        if file_path.exists():
            try:
                os.remove(file_path)
                logger.info(f"파일 삭제 완료: {file_path}")
            except Exception as file_error:
                logger.error(f"파일 삭제 실패: {file_error}")

        await db.commit()

        logger.info(
            f"평가 기준 삭제 완료: id={criteria_id}, "
            f"title={document.title}"
        )

        return CriteriaDeleteResponse(
            success=True,
            criteria_id=criteria_id,
            title=document.title,
            message=f"평가 기준 '{document.title}'이(가) 삭제되었습니다.",
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"평가 기준 삭제 실패: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"평가 기준 삭제 중 오류 발생: {e}",
        )


@router.delete("/", response_model=CriteriaDeleteAllResponse)
async def delete_all_criteria(
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    모든 평가 기준 문서 삭제

    Args:
        current_user: 현재 관리자 사용자
        db: 데이터베이스 세션

    Returns:
        전체 삭제 결과

    Raises:
        HTTPException: 삭제 실패 시
    """
    try:
        repo = CriteriaRepository(db)

        # 1. 삭제 전 문서 목록 조회
        documents, _ = await repo.list_all(page=1, page_size=1000)

        if not documents:
            return CriteriaDeleteAllResponse(
                success=True,
                deleted_count=0,
                message="삭제할 평가 기준이 없습니다.",
            )

        # 2. Vector Store 삭제 (스토어 삭제 시 내부 문서도 자동 삭제)
        embedding_service = CriteriaEmbeddingService()
        failed_vectors = []

        for doc in documents:
            if doc.vector_store_id:
                logger.info(
                    f"스토어 삭제 시작: "
                    f"title={doc.title}, "
                    f"store_id={doc.vector_store_id}"
                )
                vector_deleted = await embedding_service.delete_store(
                    doc.vector_store_id,
                    ignore_errors=False,
                )
                if not vector_deleted:
                    failed_vectors.append(
                        f"{doc.title} (Store ID: {doc.vector_store_id})"
                    )
                else:
                    logger.info(
                        f"스토어 삭제 완료: "
                        f"title={doc.title}, "
                        f"store_id={doc.vector_store_id}"
                    )

        # Vector Store 삭제 실패 시 중단
        if failed_vectors:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Vector Store 삭제 실패: "
                    f"{', '.join(failed_vectors)}. "
                    f"삭제 작업이 중단되었습니다."
                ),
            )

        # 3. Local DB 삭제 (Vector DB 삭제 성공 후에만)
        deleted_count = await repo.delete_all()

        # 4. 파일 삭제
        for doc in documents:
            file_path = Path(doc.file_path)
            if file_path.exists():
                try:
                    os.remove(file_path)
                    logger.info(f"파일 삭제 완료: {file_path}")
                except Exception as file_error:
                    logger.error(f"파일 삭제 실패: {file_error}")

        # 5. 감사 로그 기록
        audit_service = CriteriaAuditService(db)
        await audit_service.log_delete_all(
            actor_id=current_user.id,
            deleted_count=deleted_count,
        )

        await db.commit()

        logger.info(
            f"모든 평가 기준 삭제 완료: "
            f"deleted_count={deleted_count}"
        )

        return CriteriaDeleteAllResponse(
            success=True,
            deleted_count=deleted_count,
            message=f"{deleted_count}개의 평가 기준이 모두 삭제되었습니다.",
        )

    except Exception as e:
        logger.error(f"전체 평가 기준 삭제 실패: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"전체 평가 기준 삭제 중 오류 발생: {e}",
        )
