"""
QnA 라우터
질문답변 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import logging

from app.db import get_db
from app.models.users import User
from app.models.documents import Document
from app.schemas.qna import QARequest, QAResponse, QALogResponse
from app.routers.auth import get_current_user
from app.services.qna_service import QnAService

router = APIRouter()
logger = logging.getLogger(__name__)


# T047: POST /qna/{document_id} - 질문하기
@router.post("/qna/{document_id}", response_model=QAResponse)
async def ask_question(
    document_id: int,
    qa_request: QARequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """문서에 대한 질문"""
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

    if document.status != "ready":
        raise HTTPException(
            400, f"문서 상태가 'ready'가 아닙니다: {document.status}"
        )

    # store_id와 file_search_file_id 검증 (업로드 완료 여부 확인)
    if not document.store_id:
        raise HTTPException(
            409, "문서 업로드가 완료되지 않았습니다 (store_id 없음). 문서를 다시 업로드해주세요."
        )

    if not document.file_search_file_id:
        raise HTTPException(
            409, "문서 업로드가 완료되지 않았습니다 (file_search_file_id 없음). 문서를 다시 업로드해주세요."
        )

    # QnA 서비스 실행
    qna_service = QnAService(db)

    try:
        response = await qna_service.ask_question(
            document=document,
            question=qa_request.question,
            user_id=current_user.id,
        )

        await db.commit()

        return response

    except Exception as e:
        logger.error(f"QnA 처리 실패: {str(e)}")
        raise HTTPException(500, "질문 처리 중 오류가 발생했습니다")


# T048: GET /qna/{document_id} - QnA 히스토리
@router.get(
    "/qna/{document_id}", response_model=List[QALogResponse]
)
async def get_qa_history(
    document_id: int,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """문서 QnA 히스토리 조회"""
    # 문서 권한 확인
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == current_user.id,
        )
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(404, "문서를 찾을 수 없습니다")

    # QnA 히스토리 가져오기
    qna_service = QnAService(db)
    qa_logs = await qna_service.get_qa_history(
        document_id=document_id, user_id=current_user.id, limit=limit
    )

    return qa_logs
