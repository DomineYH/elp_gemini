"""
문서 평가 라우터
평가 템플릿 관리 및 평가 실행 엔드포인트
"""
import logging
from typing import List
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.models.users import User
from app.models.evaluations import (
    EvaluationTemplate,
    EvaluationRun,
)
from app.schemas.eval import (
    EvaluationRunResponse,
    EvaluationReportResponse,
    EvaluationRequest,
)
from app.routers.auth import get_current_user
from app.services.eval_service import EvaluationService
from app.utils.logging import log_user_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/eval", tags=["evaluation"])


@router.get("/templates", response_model=List[dict])
async def list_evaluation_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    활성 평가 템플릿 목록 조회

    Returns:
        평가 템플릿 목록
    """
    try:
        result = await db.execute(
            select(EvaluationTemplate).where(
                EvaluationTemplate.is_active == True
            )
        )
        templates = result.scalars().all()

        log_user_action(
            current_user.id, "list_templates", {"count": len(templates)}
        )

        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "created_at": t.created_at.isoformat(),
            }
            for t in templates
        ]

    except Exception as e:
        logger.error(f"템플릿 목록 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="템플릿 목록을 가져올 수 없습니다"
        )


@router.post("/templates/upload")
async def upload_evaluation_template(
    name: str = Form(..., description="템플릿 이름"),
    description: str = Form(None, description="템플릿 설명"),
    file: UploadFile = File(..., description="루브릭 파일 (PDF)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    평가 템플릿 업로드 (관리자 전용)

    Args:
        name: 템플릿 이름
        description: 템플릿 설명
        file: 루브릭 PDF 파일

    Returns:
        업로드된 템플릿 정보
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403, detail="관리자만 템플릿을 업로드할 수 있습니다"
        )

    # 파일 타입 검증
    if not file.filename.endswith(".pdf"):
        raise HTTPException(
            status_code=400, detail="PDF 파일만 업로드 가능합니다"
        )

    try:
        # 임시 파일로 저장
        import os
        from app.config import settings

        upload_dir = settings.UPLOAD_DIR
        os.makedirs(upload_dir, exist_ok=True)

        file_path = os.path.join(
            upload_dir, f"rubric_{name}_{file.filename}"
        )
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # 평가 서비스로 업로드
        eval_service = EvaluationService(db)
        template = await eval_service.upload_evaluation_template(
            file_path=file_path,
            name=name,
            description=description,
        )

        log_user_action(
            current_user.id, "upload_template", {"template_id": template.id}
        )

        return {
            "id": template.id,
            "name": template.name,
            "description": template.description,
        }

    except Exception as e:
        logger.error(f"템플릿 업로드 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"템플릿 업로드 실패: {str(e)}"
        )


@router.post("/run", response_model=EvaluationRunResponse)
async def run_evaluation(
    request: EvaluationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    문서 평가 실행

    Args:
        request: 평가 요청 (template_id)

    Returns:
        평가 실행 정보
    """
    try:
        # 기본 시스템 프롬프트 가져오기
        from app.models.prompts import SystemPrompt

        result = await db.execute(
            select(SystemPrompt).where(
                SystemPrompt.type == "evaluation",
                SystemPrompt.is_active == True,
            )
        )
        prompt = result.scalar_one_or_none()

        if not prompt:
            raise HTTPException(
                status_code=404, detail="활성 평가 프롬프트를 찾을 수 없습니다"
            )

        # 평가 실행
        eval_service = EvaluationService(db)
        eval_run = await eval_service.run_evaluation(
            document_id=1,  # TODO: 실제 문서 ID로 교체
            user_id=current_user.id,
            template_id=request.template_id,
            prompt_id=prompt.id,
        )

        log_user_action(
            current_user.id, "run_evaluation", {"run_id": eval_run.id}
        )

        return EvaluationRunResponse.model_validate(eval_run)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"평가 실행 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"평가 실행 실패: {str(e)}"
        )


@router.get("/runs/{run_id}", response_model=EvaluationRunResponse)
async def get_evaluation_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    평가 실행 정보 조회

    Args:
        run_id: 평가 실행 ID

    Returns:
        평가 실행 정보
    """
    try:
        eval_run = await db.get(EvaluationRun, run_id)

        if not eval_run:
            raise HTTPException(
                status_code=404, detail="평가 실행을 찾을 수 없습니다"
            )

        # 권한 확인
        if (
            eval_run.user_id != current_user.id
            and not current_user.is_admin
        ):
            raise HTTPException(
                status_code=403, detail="접근 권한이 없습니다"
            )

        return EvaluationRunResponse.model_validate(eval_run)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"평가 실행 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="평가 실행 정보를 가져올 수 없습니다"
        )


@router.get(
    "/reports/{run_id}", response_model=EvaluationReportResponse
)
async def get_evaluation_report(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    평가 보고서 조회

    Args:
        run_id: 평가 실행 ID

    Returns:
        평가 보고서
    """
    try:
        # 평가 실행 권한 확인
        eval_run = await db.get(EvaluationRun, run_id)
        if not eval_run:
            raise HTTPException(
                status_code=404, detail="평가 실행을 찾을 수 없습니다"
            )

        if (
            eval_run.user_id != current_user.id
            and not current_user.is_admin
        ):
            raise HTTPException(
                status_code=403, detail="접근 권한이 없습니다"
            )

        # 보고서 조회
        eval_service = EvaluationService(db)
        report = await eval_service.get_evaluation_report(run_id)

        if not report:
            raise HTTPException(
                status_code=404, detail="평가 보고서를 찾을 수 없습니다"
            )

        return EvaluationReportResponse.model_validate(report)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"평가 보고서 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail="평가 보고서를 가져올 수 없습니다"
        )
