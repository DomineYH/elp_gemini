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
from fastapi.responses import HTMLResponse, RedirectResponse
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

router = APIRouter()
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

    # 문서 상태별 개수 계산 (T084)
    status_counts = {}
    for doc in documents:
        status_counts[doc.status] = (
            status_counts.get(doc.status, 0) + 1
        )

    return templates.TemplateResponse(
        "user/dashboard.html",
        {
            "request": request,
            "user": current_user,
            "documents": documents,
            "total_count": len(documents),
            "status_counts": status_counts,
        },
    )


# T043: POST /docs/upload - 문서 업로드
@router.post("/docs/upload")
async def upload_document(
    request: Request,
    title: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """문서 업로드"""
    try:
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
            document.status = "failed"

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


# T044/T078/T079: GET /docs - 문서 목록 (필터링, 페이지네이션)
@router.get("/docs", response_model=List[DocumentResponse])
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


# T045: GET /docs/{document_id} - 문서 상세
@router.get("/docs/{document_id}", response_class=HTMLResponse)
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


# T046/T080/T083: DELETE /docs/{document_id} - 문서 소프트 삭제
@router.delete("/docs/{document_id}")
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
