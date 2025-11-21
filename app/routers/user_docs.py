"""
사용자 문서 라우터
문서 CRUD 엔드포인트
"""
import os
import secrets
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    FileResponse,
)
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import logging

from app.db import get_db
from app.models.users import User
from app.models.documents import Document
from app.schemas.documents import DocumentResponse
from app.routers.auth import get_current_user
from app.services.file_search_service import FileSearchService
from app.config import settings

router = APIRouter(prefix="/dashboard", tags=["documents"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


# T052/T084: GET / - 사용자 대시보드 (문서 요약 포함)
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """사용자 대시보드"""
    # 사용자 문서 목록 가져오기 (삭제된 문서 제외)
    result = await db.execute(
        select(Document)
        .where(
            Document.user_id == current_user.id,
            Document.status != "deleted",
        )
        .order_by(Document.uploaded_at.desc())
    )
    documents = result.scalars().all()

    # 활성 문서 확인 (ready 상태)
    active_doc = next(
        (doc for doc in documents if doc.status == "ready"), None
    )

    if active_doc:
        # 뷰어 렌더링
        return templates.TemplateResponse(
            "user/viewer.html",
            {
                "request": request,
                "user": current_user,
                "document": active_doc,
            },
        )
    else:
        # 업로드 화면 렌더링
        return templates.TemplateResponse(
            "user/upload.html",
            {
                "request": request,
                "user": current_user,
            },
        )


# T043: POST /upload - 문서 업로드
@router.post("/upload")
async def upload_document(
    request: Request,
    title: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """문서 업로드 (단일 문서 정책 적용)"""
    try:
        # 기존 문서 정리 (단일 문서 정책)
        # 'ready', 'indexing', 'uploading' 상태의 문서 조회
        result = await db.execute(
            select(Document).where(
                Document.user_id == current_user.id,
                Document.status.in_(["ready", "indexing", "uploading"]),
            )
        )
        existing_docs = result.scalars().all()

        fs_service = FileSearchService()

        for doc in existing_docs:
            # Vector DB에서 삭제
            if doc.file_search_file_id:
                try:
                    await fs_service.delete_document(doc.file_search_file_id)
                except Exception as e:
                    logger.warning(f"기존 문서 Vector DB 삭제 실패: {str(e)}")
            
            # DB 상태 변경 (소프트 삭제)
            doc.status = "deleted"
        
        if existing_docs:
            await db.flush()
            logger.info(f"기존 문서 {len(existing_docs)}개 정리 완료")

        # 파일 타입 검증
        if file.content_type != "application/pdf":
            raise HTTPException(400, "PDF 파일만 업로드 가능합니다")

        # 파일 크기 검증
        contents = await file.read()
        file_size = len(contents)

        if file_size > settings.MAX_UPLOAD_SIZE:
            raise HTTPException(
                400, f"파일 크기는 50MB를 초과할 수 없습니다"
            )

        # 랜덤 키 생성 (데이터 격리용)
        random_key = secrets.token_urlsafe(48)

        # 파일 저장
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        file_path = os.path.join(
            settings.UPLOAD_DIR, f"{random_key}.pdf"
        )

        with open(file_path, "wb") as f:
            f.write(contents)

        # 문서 레코드 생성
        document = Document(
            user_id=current_user.id,
            random_key=random_key,
            title=title,
            file_path=file_path,
            file_size=file_size,
            status="uploading",
        )
        db.add(document)
        await db.flush()

        # File Search에 업로드 (백그라운드로 처리 권장)
        try:
            fs_service = FileSearchService()
            result = await fs_service.upload_document(
                file_path=file_path,
                display_name=title,
                metadata={
                    "user_id": str(current_user.id),
                    "random_key": random_key,
                    "document_id": str(document.id),
                },
            )

            document.file_search_file_id = result.get("document_id")
            document.store_id = result.get("store_id")
            document.status = "ready"

        except Exception as e:
            logger.error(
                f"File Search 업로드 실패: {str(e)}",
                exc_info=True,
                extra={
                    "user_id": current_user.id,
                    "document_id": document.id,
                    "file_path": file_path,
                }
            )
            # Debug logging to file
            with open("debug_error.log", "a") as f:
                f.write(f"Upload failed: {str(e)}\n")
            document.status = "failed"

        await db.commit()

        logger.info(
            f"문서 업로드 완료: user={current_user.id}, "
            f"doc={document.id}"
        )

        return RedirectResponse(url="/", status_code=302)

        await db.commit()

        logger.info(
            f"문서 업로드 완료: user={current_user.id}, "
            f"doc={document.id}"
        )

        return RedirectResponse(url="/", status_code=302)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"문서 업로드 오류: {str(e)}")
        raise HTTPException(500, "문서 업로드 중 오류가 발생했습니다")


# T044/T078/T079: GET /list - 문서 목록 (필터링, 페이지네이션)
@router.get("/list", response_model=List[DocumentResponse])
async def list_documents(
    status: str = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "date",  # date, title
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    사용자 문서 목록 조회

    Args:
        status: 문서 상태 필터 (ready, uploading, failed 등)
        page: 페이지 번호 (1부터 시작)
        page_size: 페이지당 문서 개수 (기본 20)
        sort_by: 정렬 기준 (date=날짜순, title=제목순)

    Returns:
        문서 목록
    """
    query = select(Document).where(
        Document.user_id == current_user.id,
        Document.status != "deleted",  # 삭제된 문서 제외
    )

    # 상태 필터링
    if status:
        query = query.where(Document.status == status)

    # 정렬
    if sort_by == "title":
        query = query.order_by(Document.title.asc())
    else:  # 기본값: 날짜순
        query = query.order_by(Document.uploaded_at.desc())

    # 페이지네이션
    offset = (page - 1) * page_size
    query = query.limit(page_size).offset(offset)

    result = await db.execute(query)
    documents = result.scalars().all()
    return documents


@router.get("/{document_id}", response_class=HTMLResponse)
async def get_document(
    request: Request,
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """문서 상세 조회"""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == current_user.id,
        )
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(404, "문서를 찾을 수 없습니다")

    return templates.TemplateResponse(
        "user/doc_detail.html",
        {
            "request": request,
            "user": current_user,
            "document": document,
        },
    )


# T096: GET /{document_id}/download - 파일 다운로드
@router.get("/{document_id}/download")
async def download_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    문서 파일 다운로드

    인증된 사용자만 본인의 문서를 다운로드할 수 있습니다.

    Args:
        document_id: 문서 ID
        current_user: 현재 사용자
        db: 데이터베이스 세션

    Returns:
        파일 스트리밍 응답

    Raises:
        HTTPException: 문서를 찾을 수 없거나 권한이 없는 경우
    """
    # 문서 조회 및 권한 확인
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == current_user.id,
        )
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(404, "문서를 찾을 수 없습니다")

    # 파일 경로 확인
    file_path = document.file_path

    if not file_path or not os.path.exists(file_path):
        logger.error(
            f"파일을 찾을 수 없음: "
            f"document_id={document_id}, "
            f"path={file_path}"
        )
        raise HTTPException(404, "파일을 찾을 수 없습니다")

    # 파일명 추출 (안전한 파일명 사용)
    filename = os.path.basename(file_path)

    # 파일 다운로드 로깅
    logger.info(
        f"파일 다운로드: user_id={current_user.id}, "
        f"document_id={document_id}, "
        f"filename={filename}"
    )

    # FileResponse로 스트리밍
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


# T046/T080/T083: DELETE /docs/{document_id} - 문서 소프트 삭제
@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    문서 소프트 삭제
    실제 삭제가 아닌 status를 'deleted'로 변경
    File Search Store에서는 실제 삭제
    """
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == current_user.id,
            Document.status != "deleted",  # 이미 삭제된 문서는 제외
        )
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(404, "문서를 찾을 수 없습니다")

    # File Search에서 삭제 (T083)
    if document.file_search_file_id:
        try:
            fs_service = FileSearchService()
            await fs_service.delete_document(
                file_id=document.file_search_file_id
            )
        except Exception as e:
            logger.warning(f"File Search 삭제 실패: {str(e)}")

    # 소프트 삭제: status를 'deleted'로 변경
    document.status = "deleted"
    await db.commit()

    logger.info(f"문서 소프트 삭제 완료: doc={document_id}")

    return {"message": "문서가 삭제되었습니다"}


# T090: POST /docs/cleanup - 세션 종료 시 정리
@router.post("/cleanup")
async def cleanup_session(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    세션 종료 시 리소스 정리
    - 현재 사용자의 활성 문서 Vector DB 데이터 삭제
    """
    try:
        # 활성 문서 조회
        result = await db.execute(
            select(Document).where(
                Document.user_id == current_user.id,
                Document.status.in_(["ready", "indexing"]),
            )
        )
        active_docs = result.scalars().all()

        if not active_docs:
            return {"message": "정리할 문서가 없습니다"}

        fs_service = FileSearchService()

        for doc in active_docs:
            # Vector DB에서 삭제
            if doc.file_search_file_id:
                try:
                    await fs_service.delete_document(doc.file_search_file_id)
                except Exception as e:
                    logger.warning(f"Cleanup: Vector DB 삭제 실패: {str(e)}")
            
            # 상태 변경 (deleted)
            doc.status = "deleted"
        
        await db.commit()
        logger.info(f"세션 정리 완료: user={current_user.id}, docs={len(active_docs)}")
        
        return {"message": "세션 데이터가 정리되었습니다"}

    except Exception as e:
        logger.error(f"세션 정리 중 오류: {str(e)}")
        raise HTTPException(500, "세션 정리 실패")
