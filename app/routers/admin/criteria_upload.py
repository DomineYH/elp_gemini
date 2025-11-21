"""
평가 기준 업로드 라우터
관리자 전용 기준 문서 업로드
"""
import os
import logging
from pathlib import Path
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
)
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.db import get_db
from app.models.users import User
from app.models.criteria import CriteriaUploadResponse
from app.repositories.criteria_repository import (
    CriteriaRepository,
)
from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService,
)
from app.services.file_validator import get_file_validator
from app.services.criteria_audit_service import (
    CriteriaAuditService,
)
from app.routers.auth import get_current_admin
from app.config import settings

router = APIRouter(tags=["admin", "criteria"])
logger = logging.getLogger(__name__)


# ===== 헬퍼 함수 =====


def _save_uploaded_file(
    file: UploadFile, contents: bytes
) -> Path:
    """업로드 파일을 디스크에 저장"""
    upload_dir = Path(settings.CRITERIA_UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    import time

    timestamp = int(time.time() * 1000)
    safe_filename = (
        file.filename.replace(" ", "_")
        if file.filename
        else "file.pdf"
    )
    unique_filename = f"{timestamp}_{safe_filename}"
    file_path = upload_dir / unique_filename

    with open(file_path, "wb") as f:
        f.write(contents)

    logger.info(f"기준 문서 파일 저장: {file_path}")
    return file_path


# ===== 엔드포인트 =====


@router.post("/upload", response_model=CriteriaUploadResponse)
async def upload_criteria(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """평가 기준 문서 업로드"""
    uploaded_file_path = None

    try:
        # 파일 검증 (강화된 보안 검증)
        contents = await file.read()
        validator = get_file_validator()
        file_size, metadata = validator.validate_pdf(
            file, contents
        )

        # 검증 메타데이터 로깅
        logger.info(
            f"파일 검증 완료: size={file_size}, "
            f"metadata={metadata}"
        )

        # 제목 설정
        document_title = (
            title or file.filename or "untitled.pdf"
        ).strip()

        # 파일 저장
        uploaded_file_path = _save_uploaded_file(file, contents)

        # 임베딩 생성
        embedding_service = CriteriaEmbeddingService()
        vector_store_id, document_id = (
            await embedding_service.upload_and_embed(
                file_path=str(uploaded_file_path),
                title=document_title,
                metadata={"admin_id": current_user.id},
            )
        )

        logger.info(
            f"임베딩 완료: store_id={vector_store_id}, "
            f"doc_id={document_id}"
        )

        # DB 저장
        repo = CriteriaRepository(db)
        document = await repo.create(
            title=document_title,
            file_path=str(uploaded_file_path),
            mime_type=file.content_type,
            file_size=file_size,
            vector_store_id=vector_store_id,
            document_id=document_id,
        )

        # 감사 로그 기록
        audit_service = CriteriaAuditService(db)
        await audit_service.log_upload(
            criteria_id=document.id,
            actor_id=current_user.id,
            file_name=file.filename or "unknown.pdf",
            file_size=file_size,
            vector_store_id=vector_store_id,
        )

        await db.commit()
        await db.refresh(document)

        logger.info(
            f"기준 문서 저장: id={document.id}, "
            f"title={document.title}"
        )

        return CriteriaUploadResponse.model_validate(document)

    except HTTPException:
        raise

    except Exception as e:
        # 실패 시 클린업
        if uploaded_file_path and os.path.exists(
            uploaded_file_path
        ):
            try:
                os.remove(uploaded_file_path)
                logger.info(f"업로드 실패 - 파일 삭제")
            except Exception as cleanup_error:
                logger.error(f"클린업 실패: {cleanup_error}")

        logger.error(f"업로드 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"문서 업로드 중 오류 발생: {e}",
        )
