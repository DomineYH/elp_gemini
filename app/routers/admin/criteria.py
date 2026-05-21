"""
관리자 - 평가기준 관리 라우터
평가기준 업로드 및 삭제 엔드포인트
"""
import asyncio
import logging
import os
import tempfile
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import (
    get_current_admin,
    require_criteria_sync_ready,
)
from app.models.users import User
from app.repositories.app_state_repository import (
    KEY_LAST_SYNCED_AT,
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
    SYNC_STATE_NEEDS_RESYNC,
    AppStateRepository,
)
from app.repositories.criteria_repository import CriteriaRepository
from app.schemas.alias_map import AliasMap, AliasMapEntry, empty_alias_map
from app.schemas.criteria import validate_display_alias_text
from app.services.criteria_alias_map_service import (
    AliasMapParseError,
    CriteriaAliasMapService,
)
from app.services.criteria_reconciliation_service import (
    CriteriaReconciliationService,
    is_legacy_surrogate_stable_id,
)
from app.services.criteria_vector_service import CriteriaVectorService
from app.services.file_validator import FileValidator

router = APIRouter(
    prefix="/api/admin/criteria",
    tags=["관리자-평가기준"]
)
logger = logging.getLogger(__name__)

# alias-map 문서는 File Search store 내 단일 문서이며, replace() 가
# upload-then-delete 순서로 진행되어 수 초~수십 초 동안 두 개의 문서가
# 공존한다. 동시에 다른 mutation 의 fetch() 가 그 두 문서를 모두 보면
# AliasMapParseError 가 발생해 sync_state=needs_resync 로 떨어진다 (이슈 #78).
# 모든 alias_map 변형 경로를 이 락으로 직렬화한다.
# 단일 uvicorn 프로세스 배포 전제; 멀티 워커 시 별도 분산 락이 필요.
_alias_map_mutation_lock = asyncio.Lock()


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


async def _mark_criteria_needs_resync(db: AsyncSession, exc: Exception) -> None:
    try:
        await db.rollback()
    except Exception:
        logger.warning(
            "criteria sync_state 표시 전 rollback 실패",
            exc_info=True,
        )

    try:
        state_repo = AppStateRepository(db=db)
        await state_repo.set(KEY_SYNC_STATE, SYNC_STATE_NEEDS_RESYNC)
        await state_repo.set(KEY_SYNC_ERROR, str(exc))
        await db.commit()
    except Exception:
        logger.error(
            "criteria sync_state needs_resync 표시 실패",
            exc_info=True,
        )


async def _raise_alias_map_parse_unavailable(
    db: AsyncSession, exc: AliasMapParseError
) -> None:
    logger.error("alias_map 파싱 실패로 평가기준 동기화 필요: %s", exc)
    await _mark_criteria_needs_resync(db, exc)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="alias_map 파싱 실패 — 재동기화가 필요합니다",
    )


async def _raise_alias_map_missing_conflict(db: AsyncSession) -> None:
    exc = RuntimeError("alias_map 미존재 — 재동기화가 필요합니다")
    logger.error("alias_map 미존재로 평가기준 동기화 필요")
    await _mark_criteria_needs_resync(db, exc)
    raise HTTPException(
        status_code=409,
        detail="alias_map 미존재 — 재동기화가 필요합니다",
    )


async def _raise_criteria_mutation_failed(
    db: AsyncSession,
    exc: Exception,
    *,
    cloud_write_started: bool,
) -> None:
    if cloud_write_started:
        await _mark_criteria_needs_resync(db, exc)
    logger.error("평가기준 변경 실패: %s", exc, exc_info=True)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=(
            "평가기준 변경 중 오류가 발생했습니다: "
            f"{type(exc).__name__} - {exc}"
        ),
    )


async def _sync_criteria_db_cache_from_alias_entries(
    db: AsyncSession,
    entries: dict[str, AliasMapEntry],
    *,
    active_timestamp_override: str | None = None,
) -> None:
    repo = CriteriaRepository(db)
    for sid, entry in entries.items():
        row = await repo.get_criteria_by_stable_id(sid)
        if row:
            row.status = entry.status
            row.activated_at = (
                _parse_iso(active_timestamp_override or entry.activated_at)
                if entry.status == "active"
                else None
            )
    await db.commit()


async def _recover_status_mutation_from_cloud(
    db: AsyncSession,
    alias_svc: CriteriaAliasMapService,
    stable_id: str,
    target_status: str,
    expected_alias_map: AliasMap,
    exc: Exception,
) -> bool:
    try:
        await db.rollback()
    except Exception:
        logger.warning(
            "평가기준 상태 변경 복구 전 rollback 실패",
            exc_info=True,
        )

    try:
        fetched = await alias_svc.fetch()
    except Exception:
        logger.warning(
            "평가기준 상태 변경 실패 후 alias_map 재조회 실패",
            exc_info=True,
        )
        return False

    if fetched is None:
        return False

    _, cloud_alias_map = fetched
    entry = cloud_alias_map.entries.get(stable_id)
    if (
        cloud_alias_map.updated_at != expected_alias_map.updated_at
        or cloud_alias_map.entries != expected_alias_map.entries
        or entry is None
        or entry.status != target_status
    ):
        return False

    try:
        await _sync_criteria_db_cache_from_alias_entries(
            db,
            cloud_alias_map.entries,
        )
    except Exception:
        logger.warning(
            "평가기준 상태 변경 cloud 반영 후 DB 캐시 복구 실패",
            exc_info=True,
        )
        return False

    logger.info(
        "평가기준 상태 변경 예외 후 cloud truth 기준 복구: "
        "stable_id=%s status=%s original_error=%s",
        stable_id,
        target_status,
        exc,
    )
    return True


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
    async with _alias_map_mutation_lock:
        temp_file_path = None
        cloud_write_started = False

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
            cloud_write_started = True
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
                alias=None, status="active", activated_at=_now_iso_utc()
            )
            updated_alias_map = AliasMap(
                schema_version=1,
                updated_at=_now_iso_utc(),
                entries=new_entries,
            )
            cloud_write_started = True
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
                status="active",
                created_at=None,
                activated_at=_now_iso_utc(),
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

        except AliasMapParseError as e:
            await _raise_alias_map_parse_unavailable(db, e)
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            if cloud_write_started:
                await _mark_criteria_needs_resync(db, e)
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
                detail=(
                    "파일 업로드 중 오류가 발생했습니다: "
                    f"{error_type} - {error_msg}"
                ),
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
    "/{stable_id}",
    summary="평가기준 삭제 (stable_id 기반)",
    description="클라우드 문서 + alias_map entry + DB 행을 삭제합니다.",
)
async def delete_criteria_by_stable_id(
    stable_id: str,
    current_admin: User = Depends(get_current_admin),
    _sync_ready=Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    async with _alias_map_mutation_lock:
        repo = CriteriaRepository(db)
        row = await repo.get_criteria_by_stable_id(stable_id)
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"평가기준 stable_id={stable_id} 를 찾을 수 없습니다",
            )

        cloud_write_started = False
        try:
            vec = CriteriaVectorService()
            alias_svc = CriteriaAliasMapService(
                client=vec.file_search_service.client,
                store_display_name=settings.FS_RUBRIC_STORE_NAME,
            )
            try:
                fetched = await alias_svc.fetch()
            except AliasMapParseError as e:
                await _raise_alias_map_parse_unavailable(db, e)
            if fetched is None:
                await _raise_alias_map_missing_conflict(db)

            cloud_write_started = True
            await vec.delete_criteria(document_id=row.document_id)

            old_doc_name, alias_map = fetched
            if stable_id in alias_map.entries:
                new_entries = dict(alias_map.entries)
                new_entries.pop(stable_id, None)
                new_alias_map = AliasMap(
                    schema_version=1,
                    updated_at=_now_iso_utc(),
                    entries=new_entries,
                )
                cloud_write_started = True
                await alias_svc.replace(
                    new_alias_map, old_doc_name=old_doc_name
                )

            await db.delete(row)
            await db.commit()
            logger.info(
                f"평가기준 삭제: stable_id={stable_id} "
                f"document_id={row.document_id}"
            )
            return {"stable_id": stable_id, "deleted": True}
        except HTTPException:
            raise
        except Exception as e:
            await _raise_criteria_mutation_failed(
                db,
                e,
                cloud_write_started=cloud_write_started,
            )


@router.post(
    "/{stable_id}/replace",
    summary="평가기준 PDF 교체 (legacy → v2 마이그레이션 경로)",
    description=(
        "stable_id가 legacy surrogate인 평가기준 행을 동일/대체 PDF "
        "재업로드로 새 v2 stable_id 문서로 교체합니다. alias는 승계됩니다."
    ),
)
async def replace_legacy_criteria(
    stable_id: str,
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_admin),
    _sync_ready=Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    async with _alias_map_mutation_lock:
        if not is_legacy_surrogate_stable_id(stable_id):
            raise HTTPException(
                status_code=400,
                detail=(
                    "교체는 legacy(pre-v2) 평가기준에만 적용됩니다. "
                    "이미 v2 stable_id를 가진 행은 "
                    "일반 삭제/업로드를 사용하세요."
                ),
            )

        temp_file_path = None
        cloud_write_started = False
        try:
            validator = FileValidator()
            validation_result = await validator.validate_file(file)
            if not validation_result["valid"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=validation_result["error"],
                )

            file_content = await file.read()
            suffix = os.path.splitext(file.filename)[1]
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix
            ) as tmp:
                tmp.write(file_content)
                temp_file_path = tmp.name

            vec = CriteriaVectorService()
            alias_svc = CriteriaAliasMapService(
                client=vec.file_search_service.client,
                store_display_name=settings.FS_RUBRIC_STORE_NAME,
            )
            repo = CriteriaRepository(db)

            try:
                fetched = await alias_svc.fetch()
            except AliasMapParseError as e:
                await _raise_alias_map_parse_unavailable(db, e)
            if fetched is None:
                await _raise_alias_map_missing_conflict(db)
            old_doc_name, alias_map = fetched
            if stable_id not in alias_map.entries:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"평가기준 stable_id={stable_id} 를 찾을 수 없습니다"
                    ),
                )
            old_alias = alias_map.entries[stable_id].alias

            old_row = await repo.get_criteria_by_stable_id(stable_id)
            if not old_row:
                raise HTTPException(
                    status_code=404,
                    detail=f"DB 캐시에 stable_id={stable_id} 행이 없습니다",
                )
            old_document_id = old_row.document_id

            # 1) Cloud upload with new stable_id BEFORE any destructive op.
            new_stable_id = _new_stable_id()
            cloud_write_started = True
            upload_result = await vec.upload_criteria(
                file_path=temp_file_path,
                title=file.filename,
                stable_id=new_stable_id,
            )
            new_document_id = upload_result["document_id"]

            # 2) alias_map: remove legacy entry + add new entry
            #    (preserve alias).
            new_entries = dict(alias_map.entries)
            new_entries.pop(stable_id, None)
            new_entries[new_stable_id] = AliasMapEntry(
                alias=old_alias,
                status="active",
                activated_at=_now_iso_utc(),
            )
            new_alias_map = AliasMap(
                schema_version=1,
                updated_at=_now_iso_utc(),
                entries=new_entries,
            )
            await alias_svc.replace(new_alias_map, old_doc_name=old_doc_name)

            # 3) Delete old cloud document AFTER alias_map publish succeeded.
            await vec.delete_criteria(document_id=old_document_id)

            # 4) DB: delete old row + insert new row.
            await db.delete(old_row)
            await repo.insert(
                stable_id=new_stable_id,
                document_id=new_document_id,
                title=file.filename,
                display_alias=old_alias,
                status="active",
                created_at=None,
                activated_at=_now_iso_utc(),
                uploaded_by=current_admin.username,
            )
            await db.commit()

            logger.info(
                "평가기준 교체: legacy_stable_id=%s → new_stable_id=%s "
                "old_document_id=%s new_document_id=%s",
                stable_id, new_stable_id, old_document_id, new_document_id,
            )
            return {
                "old_stable_id": stable_id,
                "new_stable_id": new_stable_id,
                "document_id": new_document_id,
            }
        except HTTPException:
            raise
        except Exception as e:
            await _raise_criteria_mutation_failed(
                db, e, cloud_write_started=cloud_write_started,
            )
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    logger.warning("임시 파일 삭제 실패", exc_info=True)


class _AliasPatch(BaseModel):
    alias: Optional[str] = Field(default=None)

    @field_validator("alias")
    @classmethod
    def validate_alias(cls, v):
        return validate_display_alias_text(v)


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
    async with _alias_map_mutation_lock:
        cloud_write_started = False
        try:
            vec = CriteriaVectorService()
            alias_svc = CriteriaAliasMapService(
                client=vec.file_search_service.client,
                store_display_name=settings.FS_RUBRIC_STORE_NAME,
            )

            try:
                fetched = await alias_svc.fetch()
            except AliasMapParseError as e:
                await _raise_alias_map_parse_unavailable(db, e)
            if fetched is None:
                await _raise_alias_map_missing_conflict(db)
            old_doc_name, alias_map = fetched

            if stable_id not in alias_map.entries:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"평가기준 stable_id={stable_id} 를 찾을 수 없습니다"
                    ),
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
            cloud_write_started = True
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
        except HTTPException:
            raise
        except Exception as e:
            await _raise_criteria_mutation_failed(
                db,
                e,
                cloud_write_started=cloud_write_started,
            )


@router.post(
    "/{stable_id}/activate",
    summary="평가기준 활성화 (stable_id 기반)",
    description=(
        "해당 stable_id를 active로 전환합니다. 다중 active를 허용합니다."
    ),
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
    다중 active를 허용합니다.
    """
    if target_status == "active" and is_legacy_surrogate_stable_id(stable_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "Legacy(pre-v2) 평가기준은 직접 활성화할 수 없습니다. "
                "목록의 '교체' 버튼으로 동일하거나 대체할 PDF를 재업로드하면 "
                "v2 stable_id가 발급되어 활성화할 수 있습니다."
            ),
        )

    async with _alias_map_mutation_lock:
        cloud_write_started = False
        try:
            vec = CriteriaVectorService()
            alias_svc = CriteriaAliasMapService(
                client=vec.file_search_service.client,
                store_display_name=settings.FS_RUBRIC_STORE_NAME,
            )

            try:
                fetched = await alias_svc.fetch()
            except AliasMapParseError as e:
                await _raise_alias_map_parse_unavailable(db, e)
            if fetched is None:
                await _raise_alias_map_missing_conflict(db)
            old_doc_name, alias_map = fetched
            if stable_id not in alias_map.entries:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"평가기준 stable_id={stable_id} 를 찾을 수 없습니다"
                    ),
                )

            now = _now_iso_utc()
            new_entries: dict = {}
            for sid, entry in alias_map.entries.items():
                if sid == stable_id:
                    new_entries[sid] = entry.model_copy(update={
                        "status": target_status,
                        "activated_at": (
                            now if target_status == "active" else None
                        ),
                    })
                else:
                    new_entries[sid] = entry

            new_alias_map = AliasMap(
                schema_version=1, updated_at=now, entries=new_entries
            )
            cloud_write_started = True
            await alias_svc.replace(new_alias_map, old_doc_name=old_doc_name)

            # Sync DB cache for all entries
            await _sync_criteria_db_cache_from_alias_entries(
                db,
                new_entries,
                active_timestamp_override=now,
            )

            logger.info(
                f"상태 변경: stable_id={stable_id} status={target_status}"
            )
            return {"stable_id": stable_id, "status": target_status}
        except HTTPException:
            raise
        except Exception as e:
            if (
                cloud_write_started
                and await _recover_status_mutation_from_cloud(
                    db,
                    alias_svc,
                    stable_id,
                    target_status,
                    new_alias_map,
                    e,
                )
            ):
                return {"stable_id": stable_id, "status": target_status}

            await _raise_criteria_mutation_failed(
                db,
                e,
                cloud_write_started=cloud_write_started,
            )


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
                "stable_id": c.stable_id,
                "title": c.title,
                "display_alias": c.display_alias,
                "status": c.status,
                "file_size": c.file_size,
                "created_at": (
                    c.created_at.isoformat() if c.created_at else None
                ),
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
    async with _alias_map_mutation_lock:
        from app.config import settings
        from app.services.criteria_alias_map_service import (
            CriteriaAliasMapService,
        )

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
