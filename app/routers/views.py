"""
HTML 뷰 라우터
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import logging

from app.dependencies import get_current_user
from app.models.users import User
from app.services.lessonplan_storage_service import LessonPlanStorageService
from app.services.file_search_service import FileSearchService, _sanitize_display_name
from app.services.criteria_vector_service import CriteriaVectorService
from datetime import datetime
import shutil
import os
from pathlib import Path
from fastapi import UploadFile, File, status
from pypdf import PdfReader

router = APIRouter(tags=["뷰"])
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/templates")


@router.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="사용자 대시보드",
    description="사용자 대시보드 페이지"
)
async def user_dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    사용자 대시보드

    Args:
        request: FastAPI Request 객체
        current_user: 현재 로그인한 사용자

    Returns:
        사용자 대시보드 HTML 페이지
    """
    logger.info(f"사용자 대시보드 접근: user={current_user.username}")

    # 평가 기준 목록 조회
    criteria_service = CriteriaVectorService()
    criteria_documents = await criteria_service.list_criteria_documents()

    return templates.TemplateResponse(
        "user/dashboard.html",
        {
            "request": request,
            "user": current_user,
            "criteria_documents": criteria_documents,
        }
    )


@router.post(
    "/dashboard/upload",
    response_class=HTMLResponse,
    summary="문서 업로드 처리",
    description="PDF 문서를 업로드하고 텍스트를 추출하여 표시합니다."
)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    문서 업로드 및 처리
    1. 파일 저장
    2. PDF 텍스트 추출
    3. File Search Tool 업로드 (비동기)
    4. 로컬 파일 삭제
    5. 결과 페이지 렌더링
    """
    logger.info(f"문서 업로드 요청: user={current_user.username}, file={file.filename}")

    if not file.filename.endswith('.pdf'):
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "status_code": 400,
                "detail": "PDF 파일만 업로드 가능합니다.",
            },
            status_code=400,
        )

    # 파일 저장 경로 설정 (static/uploads)
    upload_dir = Path("app/static/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # 파일명 안전하게 처리 (ASCII 변환으로 Google API 호환성 보장)
    safe_username = _sanitize_display_name(current_user.username)
    safe_original = _sanitize_display_name(file.filename)
    saved_filename = f"{safe_username}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{safe_original}"
    file_path = upload_dir / saved_filename
    
    # 웹 접근 URL
    file_url = f"/static/uploads/{saved_filename}"

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # PDF 텍스트 추출
        reader = PdfReader(str(file_path))
        extracted_text = ""
        for page in reader.pages:
            extracted_text += page.extract_text() + "\n"

        # File Search Service 업로드
        file_search_service = FileSearchService()
        
        # 기존 스토어 정리 (새 문서 업로드 시 이전 스토어 삭제)
        store_name = f"user-{current_user.username}-store"
        await file_search_service.delete_store_by_display_name(store_name)

        # 메타데이터 설정
        metadata = {
            "user_id": current_user.username,
            "original_filename": file.filename,
            "uploaded_at": datetime.now().isoformat(),
            "type": "user_document"
        }

        # Google Store에 업로드
        result = await file_search_service.upload_document(
            file_path=str(file_path),
            display_name=file.filename,
            metadata=metadata
        )

        logger.info(f"File Search 업로드 완료: {result}")

        # 문서 정보 구성
        document = {
            "id": result["document_id"],
            "title": file.filename,
            "status": "ready",
            "uploaded_at": datetime.now(),
            "file_size": os.path.getsize(file_path),
            "content": extracted_text,
            "store_id": result["store_id"],
            "file_url": file_url
        }

        # 평가 기준 목록 조회
        criteria_service = CriteriaVectorService()
        criteria_documents = await criteria_service.list_criteria_documents()

        return templates.TemplateResponse(
            "user/dashboard.html",
            {
                "request": request,
                "user": current_user,
                "document": document,
                "extracted_text": extracted_text,
                "criteria_documents": criteria_documents,
            }
        )

    except Exception as e:
        logger.error(f"문서 처리 실패: {str(e)}", exc_info=True)
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "status_code": 500,
                "detail": f"문서 처리 중 오류가 발생했습니다: {str(e)}",
            },
            status_code=500,
        )
    finally:
        # 파일은 static/uploads에 유지하므로 삭제하지 않음
        pass


@router.post(
    "/dashboard/cleanup",
    summary="사용자 데이터 정리",
    description="사용자의 Vector Store 및 임시 데이터를 정리합니다."
)
async def cleanup_dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    대시보드 정리 (페이지 이탈/종료 시 호출)
    """
    try:
        file_search_service = FileSearchService()
        store_name = f"user-{current_user.username}-store"
        
        # 사용자 스토어 삭제
        await file_search_service.delete_store_by_display_name(store_name)
        
        logger.info(f"대시보드 정리 완료: user={current_user.username}")
        return {"status": "success", "message": "Cleanup completed"}
    except Exception as e:
        logger.error(f"대시보드 정리 실패: {str(e)}")
        return {"status": "error", "message": str(e)}
