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
import logging
import tempfile
import os

from app.db import get_db
from app.dependencies import get_current_admin
from app.models.users import User
from app.schemas.criteria import (
    UploadCriteriaResponse,
    DeleteCriteriaResponse,
    DeleteSingleCriteriaResponse,
)
from app.services.criteria_vector_service import (
    CriteriaVectorService
)
from app.services.file_validator import FileValidator
from app.repositories.criteria_repository import (
    CriteriaRepository
)

router = APIRouter(
    prefix="/api/admin/criteria",
    tags=["관리자-평가기준"]
)
logger = logging.getLogger(__name__)


@router.post(
    "/upload",
    response_model=UploadCriteriaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="평가기준 업로드",
    description="평가기준 파일을 Vector DB에 업로드합니다. "
    "(관리자 전용)",
)
async def upload_criteria(
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
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

        # 3단계: DB에 메타데이터 먼저 저장 (ID 생성용)
        logger.debug("3단계: DB에 메타데이터 저장 시작")
        criteria_repo = CriteriaRepository(db)
        
        # 임시 file_path로 저장 (나중에 업데이트)
        criteria = await criteria_repo.save_criteria(
            title=file.filename,
            file_size=len(file_content),
            uploaded_by=current_admin.username,
            file_path="temp",  # 임시 값
            document_id=None,  # 활성화 확정 전에는 None
            status="uploaded",
        )
        await db.commit()
        logger.debug(
            f"3단계: DB 메타데이터 저장 완료 - "
            f"criteria_id={criteria.id}"
        )

        # 4단계: 로컬 파일 저장
        logger.debug("4단계: 로컬 파일 저장 시작")
        from app.services.file_storage_service import (
            FileStorageService
        )
        storage = FileStorageService()
        file_path = storage.save_file(
            file_content,
            criteria.id,
            file.filename
        )
        
        # DB에 실제 file_path 업데이트
        criteria.file_path = file_path
        await db.commit()
        logger.debug(
            f"4단계: 로컬 파일 저장 완료 - "
            f"path={file_path}"
        )

        logger.info(
            f"평가기준 업로드 성공: "
            f"admin={current_admin.username}, "
            f"file={file.filename}, "
            f"criteria_id={criteria.id}"
        )

        return UploadCriteriaResponse(
            file_id=str(criteria.id),  # criteria ID 사용
            display_name=file.filename,
            file_size=len(file_content),
            upload_status="completed",
        )

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


@router.post(
    "/{criteria_id}/activate",
    summary="평가기준 활성화",
    description="특정 평가기준을 활성화합니다. Vector Store 반영은 '활성화 확정'에서 수행됩니다.",
)
async def activate_criteria(
    criteria_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    평가기준 활성화 (관리자 전용)
    
    Args:
        criteria_id: 활성화할 평가기준 ID
        current_admin: 현재 로그인한 관리자
        db: 데이터베이스 세션
        
    Returns:
        활성화 결과
    """
    try:
        criteria_repo = CriteriaRepository(db)
        criteria = await criteria_repo.activate_criteria(criteria_id)
        
        if not criteria:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="평가기준을 찾을 수 없습니다."
            )

        # DB만 커밋 (Vector Store 동기화는 confirm-activation에서 수행)
        await db.commit()

        logger.info(
            f"평가기준 활성화 (DB만): "
            f"admin={current_admin.username}, id={criteria_id}"
        )

        return {
            "success": True,
            "message": f"{criteria.title}이(가) 활성화되었습니다. '활성화 확정'을 눌러 반영하세요.",
            "criteria_id": criteria_id,
            "needs_sync": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"평가기준 활성화 실패: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="활성화 중 오류가 발생했습니다."
        )


@router.post(
    "/{criteria_id}/deactivate",
    summary="평가기준 비활성화",
    description="특정 평가기준을 비활성화합니다. Vector Store 반영은 '활성화 확정'에서 수행됩니다.",
)
async def deactivate_criteria(
    criteria_id: int,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    평가기준 비활성화 (관리자 전용)

    Args:
        criteria_id: 비활성화할 평가기준 ID
        current_admin: 현재 로그인한 관리자
        db: 데이터베이스 세션

    Returns:
        비활성화 결과
    """
    try:
        criteria_repo = CriteriaRepository(db)
        criteria = await criteria_repo.deactivate_criteria(criteria_id)

        if not criteria:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="평가기준을 찾을 수 없습니다."
            )

        # DB만 커밋 (Vector Store 동기화는 confirm-activation에서 수행)
        await db.commit()

        logger.info(
            f"평가기준 비활성화 (DB만): "
            f"admin={current_admin.username}, id={criteria_id}"
        )

        return {
            "success": True,
            "message": f"{criteria.title}이(가) 비활성화되었습니다. '활성화 확정'을 눌러 반영하세요.",
            "criteria_id": criteria_id,
            "needs_sync": True
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"평가기준 비활성화 실패: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="비활성화 중 오류가 발생했습니다."
        )


@router.post(
    "/confirm-activation",
    summary="활성화 확정 (수동 동기화)",
    description="활성화된 평가기준들을 Vector Store에 강제로 재동기화합니다.",
)
async def confirm_activation(
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    활성화 확정 (관리자 전용)
    
    활성화된 평가기준들을 Vector Store에 업로드합니다.
    (자동 동기화가 실패했을 경우 등을 위한 수동 트리거)
    
    Args:
        current_admin: 현재 로그인한 관리자
        db: 데이터베이스 세션
        
    Returns:
        확정 결과
    """
    try:
        count = await _sync_criteria_store(db, current_admin.username)
        await db.commit()
        
        return {
            "success": True,
            "message": f"{count}개의 평가기준이 동기화되었습니다.",
            "count": count
        }
        
    except Exception as e:
        await db.rollback()
        logger.error(f"활성화 확정 실패: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="활성화 확정 중 오류가 발생했습니다."
        )


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
