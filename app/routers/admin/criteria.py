"""
관리자 - 평가기준 관리 라우터
평가기준 업로드 및 삭제 엔드포인트
"""
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional
import logging
import tempfile
import os

from app.db import get_db
from app.dependencies import (
    get_current_admin,
    require_criteria_sync_ready,
)
from app.models.users import User
from app.repositories.app_state_repository import (
    AppStateRepository,
    KEY_LAST_SYNCED_AT,
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
    SYNC_STATE_NEEDS_RESYNC,
)
from app.schemas.criteria import (
    DeleteCriteriaResponse,
    DeleteSingleCriteriaResponse,
    UpdateDisplayAliasRequest,
    UpdateDisplayAliasResponse,
)
from app.services.criteria_manifest_service import (
    CloudUnavailable,
    CriteriaManifestService,
)
from app.services.criteria_reconciliation_service import (
    CriteriaReconciliationService,
)
from app.services.criteria_vector_service import (
    CriteriaVectorService
)
from app.services.file_validator import FileValidator
from app.repositories.criteria_repository import (
    CriteriaRepository
)
from app.schemas.alias_map import (
    AliasMap,
    AliasMapEntry,
    empty_alias_map,
)
from app.services.criteria_alias_map_service import (
    CriteriaAliasMapService,
)
from app.config import settings

router = APIRouter(
    prefix="/api/admin/criteria",
    tags=["관리자-평가기준"]
)
logger = logging.getLogger(__name__)


def _new_stable_id() -> str:
    """26-char base32 ULID-ish (timestamp + random). Opaque to the system."""
    import base64
    import secrets
    import time
    ts = int(time.time() * 1000).to_bytes(6, "big")
    rand = secrets.token_bytes(10)
    return base64.b32encode(ts + rand).decode("ascii").rstrip("=")


def _now_iso_utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _publish_or_mark_resync(
    criteria_repo: CriteriaRepository,
    db: AsyncSession,
) -> None:
    """매니페스트 publish 시도; 실패하면 sync_state=needs_resync 저장 후 502."""
    try:
        manifest_svc = CriteriaManifestService()
        await manifest_svc.publish_from_db(criteria_repo)
    except CloudUnavailable as e:
        state_repo = AppStateRepository(db=db)
        await state_repo.set(KEY_SYNC_STATE, SYNC_STATE_NEEDS_RESYNC)
        await state_repo.set(KEY_SYNC_ERROR, str(e))
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "변경은 저장되었으나 클라우드 동기화에 실패했습니다. "
                "관리자 페이지에서 재동기화하세요."
            ),
        )


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    summary="평가기준 업로드",
    description="평가기준 파일을 Vector DB에 업로드합니다. "
    "(관리자 전용)",
)
async def upload_criteria(
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    _sync_ready=Depends(require_criteria_sync_ready),
):
    """
    평가기준 업로드 (관리자 전용)

    Args:
        file: 업로드할 파일
        current_admin: 현재 로그인한 관리자

    Returns:
        업로드 결과 정보

    Raises:
        HTTPException: 파일 검증 실패 또는 업로드 오류
    """
    temp_file_path = None

    try:
        logger.info(
            f"평가기준 업로드 시작: "
            f"admin={current_admin.username}, "
            f"file={file.filename}"
        )

        # 파일 검증
        logger.debug("1단계: 파일 검증 시작")
        validator = FileValidator()
        validation_result = await validator.validate_file(file)

        if not validation_result["valid"]:
            logger.warning(
                f"파일 검증 실패: {validation_result['error']}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=validation_result["error"]
            )
        logger.debug("1단계: 파일 검증 완료")

        # 임시 파일로 저장
        logger.debug("2단계: 임시 파일 저장 시작")
        file_content = await file.read()
        suffix = os.path.splitext(file.filename)[1]

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix
        ) as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name

        logger.debug(
            f"2단계: 임시 파일 저장 완료 - "
            f"path={temp_file_path}, size={len(file_content)}"
        )

        # 3단계: 클라우드 업로드 (stable_id 발급)
        logger.debug("3단계: 클라우드 업로드 시작")
        stable_id = _new_stable_id()
        criteria_service = CriteriaVectorService()
        upload_result = await criteria_service.upload_criteria(
            file_path=temp_file_path,
            title=file.filename,
            stable_id=stable_id,
        )
        document_id = upload_result["document_id"]
        logger.debug(
            f"3단계: 클라우드 업로드 완료 - "
            f"stable_id={stable_id}, document_id={document_id}"
        )

        # 4단계: alias_map 업데이트 + 재게시
        logger.debug("4단계: alias_map 업데이트 시작")
        alias_svc = CriteriaAliasMapService(
            client=criteria_service.file_search_service.client,
            store_display_name=settings.FS_RUBRIC_STORE_NAME,
        )
        fetched = await alias_svc.fetch()
        old_doc_name, alias_map = (
            fetched if fetched else (None, empty_alias_map(_now_iso_utc()))
        )
        new_entries = dict(alias_map.entries)
        new_entries[stable_id] = AliasMapEntry(
            alias=None, status="uploaded", activated_at=None
        )
        updated_alias_map = AliasMap(
            schema_version=1,
            updated_at=_now_iso_utc(),
            entries=new_entries,
        )
        await alias_svc.replace(
            updated_alias_map, old_doc_name=old_doc_name
        )
        logger.debug("4단계: alias_map 재게시 완료")

        # 5단계: DB 행 삽입 (cloud is source of truth; 로컬 파일 미사용)
        logger.debug("5단계: DB 행 삽입 시작")
        criteria_repo = CriteriaRepository(db)
        await criteria_repo.insert(
            stable_id=stable_id,
            document_id=document_id,
            title=file.filename,
            display_alias=None,
            status="uploaded",
            created_at=None,
            activated_at=None,
            uploaded_by=current_admin.username,
        )
        await db.commit()
        logger.debug("5단계: DB 행 삽입 완료")

        logger.info(
            f"평가기준 업로드 성공: "
            f"admin={current_admin.username}, "
            f"file={file.filename}, "
            f"stable_id={stable_id}, "
            f"document_id={document_id}"
        )

        return {
            "stable_id": stable_id,
            "document_id": document_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        error_type = type(e).__name__
        error_msg = str(e)
        logger.error(
            f"평가기준 업로드 실패 - "
            f"유형: {error_type}, "
            f"메시지: {error_msg}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"파일 업로드 중 오류가 발생했습니다: {error_type} - {error_msg}"
        )
    finally:
        # 임시 파일 삭제
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as e:
                logger.warning(
                    f"임시 파일 삭제 실패: {e}"
                )


@router.delete(
    "",
    response_model=DeleteCriteriaResponse,
    summary="평가기준 삭제",
    description="모든 평가기준을 삭제합니다. (관리자 전용)",
)
async def delete_all_criteria(
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    _sync_ready=Depends(require_criteria_sync_ready),
):
    """
    모든 평가기준 삭제 (관리자 전용)

    Note:
        Gemini File Search API 제약으로
        개별 문서 삭제 불가 → Store 재생성으로 전체 삭제

    Args:
        current_admin: 현재 로그인한 관리자

    Returns:
        삭제 결과 정보

    Raises:
        HTTPException: 삭제 오류
    """
    try:
        # Vector Store 삭제
        criteria_service = CriteriaVectorService()
        success = await criteria_service.delete_all_criteria()

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="평가기준 삭제 실패"
            )

        # DB에서도 삭제
        criteria_repo = CriteriaRepository(db)
        deleted_count = await criteria_repo.delete_all_criteria()
        await db.commit()

        logger.info(
            f"평가기준 전체 삭제 성공: "
            f"admin={current_admin.username}, "
            f"deleted_count={deleted_count}"
        )

        await _publish_or_mark_resync(criteria_repo, db)

        return DeleteCriteriaResponse(
            success=True,
            message="모든 평가기준이 삭제되었습니다.",
            deleted_count=deleted_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            f"평가기준 삭제 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="삭제 중 오류가 발생했습니다."
        )


@router.delete(
    "/{criteria_id}",
    response_model=DeleteSingleCriteriaResponse,
    summary="평가기준 개별 삭제",
    description="특정 평가기준을 삭제합니다. "
    "활성 상태인 경우 Vector Store도 동기화됩니다.",
)
async def delete_single_criteria(
    criteria_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    _sync_ready=Depends(require_criteria_sync_ready),
):
    """
    개별 평가기준 삭제 (관리자 전용)

    Note:
        Gemini File Search API 제약으로 개별 문서 삭제 불가.
        활성 상태 평가기준 삭제 시 Vector Store를 재동기화합니다.

    Args:
        criteria_id: 삭제할 평가기준 ID
        current_admin: 현재 로그인한 관리자
        db: 데이터베이스 세션

    Returns:
        삭제 결과 정보

    Raises:
        HTTPException: 삭제 오류
    """
    try:
        criteria_repo = CriteriaRepository(db)
        
        # 평가기준 존재 확인
        criteria = await criteria_repo.get_criteria_by_id(
            criteria_id
        )
        
        if not criteria:
            logger.warning(
                f"평가기준 삭제 실패 (없음): id={criteria_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="평가기준을 찾을 수 없습니다."
            )
        
        # 활성 상태 여부 저장
        was_active = criteria.status == "active"
        criteria_title = criteria.title

        # 로컬 파일 삭제
        from app.services.file_storage_service import (
            FileStorageService
        )
        storage = FileStorageService()
        storage.delete_file(criteria.file_path)

        # DB에서 삭제
        success = await criteria_repo.delete_criteria(criteria_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="평가기준 삭제 실패"
            )

        # flush()로 DELETE를 즉시 적용 (commit 전)
        # 이후 _sync_criteria_store의 get_active_criteria가 정확한 결과 반환
        await db.flush()

        # 활성 상태였다면 Vector Store 재동기화
        sync_message = ""
        if was_active:
            try:
                sync_count = await _sync_criteria_store(
                    db, current_admin.username
                )
                sync_message = f" (Vector Store 동기화: {sync_count}개 문서)"
            except Exception as e:
                logger.warning(f"Vector Store 동기화 실패: {e}")
                sync_message = " (Vector Store 동기화 실패 - 수동 동기화 필요)"

        await db.commit()

        logger.info(
            f"평가기준 삭제 성공: "
            f"admin={current_admin.username}, "
            f"id={criteria_id}, "
            f"title={criteria_title}"
        )

        await _publish_or_mark_resync(criteria_repo, db)

        return DeleteSingleCriteriaResponse(
            success=True,
            message=f"{criteria_title} 기준이 삭제되었습니다.{sync_message}",
            criteria_id=criteria_id,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            f"평가기준 삭제 실패: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="삭제 중 오류가 발생했습니다."
        )


async def _sync_criteria_store(
    db: AsyncSession,
    admin_username: str
) -> int:
    """
    평가기준 Vector Store 동기화 (내부 헬퍼)
    
    활성화된 모든 평가기준을 Vector Store에 재업로드합니다.
    
    Args:
        db: DB 세션
        admin_username: 관리자 사용자명 (로깅용)
        
    Returns:
        동기화된 문서 수
    """
    criteria_repo = CriteriaRepository(db)
    
    # 활성 평가기준 조회
    active_criteria_list = await criteria_repo.get_active_criteria()
    
    logger.info(
        f"평가기준 동기화 시작: "
        f"{len(active_criteria_list)}개 문서 (by {admin_username})"
    )
    
    # Vector Store 재생성
    criteria_service = CriteriaVectorService()
    await criteria_service.delete_all_criteria()
    
    if not active_criteria_list:
        logger.info("활성화된 평가기준이 없어 빈 Store로 초기화됨")
        return 0
    
    # 각 active 문서를 Vector Store에 업로드
    for criteria in active_criteria_list:
        try:
            # 파일 읽기
            if not os.path.exists(criteria.file_path):
                logger.error(f"파일 없음: {criteria.file_path}")
                continue
                
            with open(criteria.file_path, "rb") as f:
                file_content = f.read()
            
            # 임시 파일 생성
            suffix = os.path.splitext(criteria.title)[1]
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix
            ) as temp_file:
                temp_file.write(file_content)
                temp_path = temp_file.name
            
            try:
                # Vector Store 업로드
                result = await criteria_service.upload_criteria(
                    file_path=temp_path,
                    display_name=criteria.title,
                    metadata={
                        "uploaded_by": criteria.uploaded_by,
                        "criteria_id": criteria.id,
                    },
                    # Store는 처음에 한 번만 재생성했으므로 여기선 유지
                    recreate_store=False,
                )
                
                # DB에 document_id 저장
                await criteria_repo.update_document_id(
                    criteria.id,
                    result["document_id"]
                )

                # 동기화 시각 업데이트
                await criteria_repo.update_synced_at(criteria.id)

                logger.info(f"Vector Store 업로드 완료: {criteria.title}")
                
            finally:
                # 임시 파일 삭제
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    
        except Exception as e:
            logger.error(
                f"문서 업로드 실패: {criteria.title}, 오류: {str(e)}",
                exc_info=True
            )
            continue
    
    return len(active_criteria_list)


@router.get(
    "/sync-status",
    summary="동기화 상태 확인",
    description="Vector Store 동기화 상태를 확인합니다.",
)
async def get_sync_status(
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    동기화 상태 확인 (관리자 전용)

    Returns:
        동기화 상태 정보
    """
    criteria_repo = CriteriaRepository(db)
    active_criteria = await criteria_repo.get_active_criteria()
    pending_criteria = await criteria_repo.get_criteria_needing_sync()

    return {
        "needs_sync": len(pending_criteria) > 0,
        "active_count": len(active_criteria),
        "pending_count": len(pending_criteria),
        "pending_titles": [c.title for c in pending_criteria]
    }


@router.patch(
    "/{criteria_id}/display-alias",
    response_model=UpdateDisplayAliasResponse,
    summary="평가기준 표시명(alias) 업데이트",
    description=(
        "DB-only 업데이트. 클라우드 재업로드 없음. "
        "ASCII printable 또는 한글 문자만 허용. "
        "NULL/빈 문자열로 보내면 alias 제거."
    ),
)
async def update_display_alias(
    criteria_id: int,
    payload: UpdateDisplayAliasRequest,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    _sync_ready=Depends(require_criteria_sync_ready),
):
    """관리자 전용. DB만 업데이트."""
    try:
        repo = CriteriaRepository(db)
        updated = await repo.update_display_alias(
            criteria_id, payload.display_alias
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="평가기준을 찾을 수 없습니다.",
            )
        await db.commit()
        logger.info(
            f"display_alias 업데이트: "
            f"admin={current_admin.username}, "
            f"id={criteria_id}, alias={payload.display_alias!r}"
        )

        await _publish_or_mark_resync(repo, db)

        return UpdateDisplayAliasResponse(
            success=True,
            criteria_id=criteria_id,
            display_alias=updated.display_alias,
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            f"display_alias 업데이트 실패: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="표시명 업데이트 중 오류가 발생했습니다.",
        )


class _AliasPatch(BaseModel):
    alias: Optional[str] = Field(default=None, max_length=255)


@router.patch(
    "/{stable_id}/alias",
    summary="평가기준 표시 이름 편집 (stable_id 기반)",
    description="alias_map 문서를 업데이트하고 DB 캐시를 동기화합니다.",
)
async def patch_criteria_alias(
    stable_id: str,
    body: _AliasPatch,
    current_admin: User = Depends(get_current_admin),
    _sync_ready=Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    vec = CriteriaVectorService()
    alias_svc = CriteriaAliasMapService(
        client=vec.file_search_service.client,
        store_display_name=settings.FS_RUBRIC_STORE_NAME,
    )

    fetched = await alias_svc.fetch()
    if not fetched:
        raise HTTPException(
            status_code=409,
            detail="alias_map 미존재 — 재동기화가 필요합니다",
        )
    old_doc_name, alias_map = fetched

    if stable_id not in alias_map.entries:
        raise HTTPException(
            status_code=404,
            detail=f"평가기준 stable_id={stable_id} 를 찾을 수 없습니다",
        )

    # Update the entry's alias only
    updated_entry = alias_map.entries[stable_id].model_copy(
        update={"alias": body.alias}
    )
    new_entries = dict(alias_map.entries)
    new_entries[stable_id] = updated_entry

    new_alias_map = AliasMap(
        schema_version=1,
        updated_at=_now_iso_utc(),
        entries=new_entries,
    )
    await alias_svc.replace(new_alias_map, old_doc_name=old_doc_name)

    # Sync DB cache
    repo = CriteriaRepository(db)
    row = await repo.get_criteria_by_stable_id(stable_id)
    if row:
        row.display_alias = body.alias
        await db.commit()

    logger.info(
        f"alias 변경: stable_id={stable_id} alias={body.alias}"
    )
    return {"stable_id": stable_id, "alias": body.alias}


@router.post(
    "/{stable_id}/activate",
    summary="평가기준 활성화 (stable_id 기반)",
    description="해당 stable_id를 active로 전환하고 기존 active는 uploaded로 강등합니다.",
)
async def activate_by_stable_id(
    stable_id: str,
    current_admin: User = Depends(get_current_admin),
    _sync_ready=Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    return await _set_status_by_stable_id(db, stable_id, "active")


@router.post(
    "/{stable_id}/deactivate",
    summary="평가기준 비활성화 (stable_id 기반)",
    description="해당 stable_id를 uploaded 상태로 변경합니다.",
)
async def deactivate_by_stable_id(
    stable_id: str,
    current_admin: User = Depends(get_current_admin),
    _sync_ready=Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    return await _set_status_by_stable_id(db, stable_id, "uploaded")


async def _set_status_by_stable_id(
    db: AsyncSession, stable_id: str, target_status: str
) -> dict:
    """
    alias_map과 DB 캐시를 동시에 업데이트.
    target_status == 'active'이면 기존 active는 'uploaded'로 강등 (단일 활성 불변).
    """
    vec = CriteriaVectorService()
    alias_svc = CriteriaAliasMapService(
        client=vec.file_search_service.client,
        store_display_name=settings.FS_RUBRIC_STORE_NAME,
    )
    fetched = await alias_svc.fetch()
    if not fetched:
        raise HTTPException(
            status_code=409,
            detail="alias_map 미존재 — 재동기화가 필요합니다",
        )
    old_doc_name, alias_map = fetched
    if stable_id not in alias_map.entries:
        raise HTTPException(
            status_code=404,
            detail=f"평가기준 stable_id={stable_id} 를 찾을 수 없습니다",
        )

    now = _now_iso_utc()
    new_entries: dict = {}
    for sid, entry in alias_map.entries.items():
        if sid == stable_id:
            new_entries[sid] = entry.model_copy(update={
                "status": target_status,
                "activated_at": now if target_status == "active" else None,
            })
        elif target_status == "active" and entry.status == "active":
            new_entries[sid] = entry.model_copy(update={
                "status": "uploaded",
                "activated_at": None,
            })
        else:
            new_entries[sid] = entry

    new_alias_map = AliasMap(
        schema_version=1, updated_at=now, entries=new_entries
    )
    await alias_svc.replace(new_alias_map, old_doc_name=old_doc_name)

    # Sync DB cache for both the target and any demoted entries
    repo = CriteriaRepository(db)
    parsed_now = _parse_iso(now)
    for sid, entry in new_entries.items():
        row = await repo.get_criteria_by_stable_id(sid)
        if row:
            row.status = entry.status
            row.activated_at = parsed_now if entry.status == "active" else None
    await db.commit()

    logger.info(f"상태 변경: stable_id={stable_id} status={target_status}")
    return {"stable_id": stable_id, "status": target_status}


def _parse_iso(value):
    """ISO-8601 string → datetime; None on failure."""
    from datetime import datetime
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


@router.get(
    "",
    summary="평가기준 목록 (JSON)",
    description="평가기준 목록과 클라우드 동기화 상태를 반환합니다.",
)
async def list_criteria_json(
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """평가기준 목록 + sync 메타데이터 (JSON)."""
    criteria_repo = CriteriaRepository(db)
    all_criteria = await criteria_repo.get_all_criteria()

    state_repo = AppStateRepository(db=db)
    sync = {
        "state": await state_repo.get(KEY_SYNC_STATE),
        "last_synced_at": await state_repo.get(KEY_LAST_SYNCED_AT),
        "error": await state_repo.get(KEY_SYNC_ERROR),
    }

    return {
        "criteria": [
            {
                "id": c.id,
                "title": c.title,
                "display_alias": c.display_alias,
                "status": c.status,
                "file_size": c.file_size,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "document_id": c.document_id,
            }
            for c in all_criteria
        ],
        "sync": sync,
    }


@router.post(
    "/reconcile",
    summary="평가기준 클라우드 재동기화",
    description="API key 변경/오류 후 클라우드에서 평가기준을 다시 가져옵니다.",
)
async def reconcile_criteria(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """클라우드 reconcile 실행."""
    from app.config import settings
    from app.services.criteria_alias_map_service import CriteriaAliasMapService

    state_repo = AppStateRepository(db=db)
    criteria_repo = CriteriaRepository(db=db)
    vector_svc = CriteriaVectorService()
    alias_svc = CriteriaAliasMapService(
        client=vector_svc.file_search_service.client,
        store_display_name=settings.FS_RUBRIC_STORE_NAME,
    )
    svc = CriteriaReconciliationService(
        db=db,
        vector_service=vector_svc,
        alias_map_service=alias_svc,
        criteria_repo=criteria_repo,
        app_state_repo=state_repo,
    )
    result = await svc.reconcile()
    return {
        "ok": result.ok,
        "skipped": result.skipped,
        "count": result.count,
        "error": result.error,
        "sync_state": await state_repo.get(KEY_SYNC_STATE),
        "last_synced_at": await state_repo.get(KEY_LAST_SYNCED_AT),
    }
