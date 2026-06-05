"""
관리자 - 프롬프트 관리 뷰 라우터
"""
from datetime import datetime
from dataclasses import dataclass
from fastapi import (
    APIRouter,
    Request,
    Depends,
    HTTPException,
)
from fastapi.responses import HTMLResponse
import logging

from app.dependencies import get_current_admin
from app.models.users import User
from app.schemas.prompts import (
    SystemPromptCreateRequest,
    SystemPromptUpdateRequest,
)
from app.services.prompt_loader_service import (
    PromptLoaderService,
)
from app.templating import templates

router = APIRouter(
    prefix="/admin",
    tags=["관리자-프롬프트"]
)
logger = logging.getLogger(__name__)

_prompt_loader = None


def _get_prompt_loader() -> PromptLoaderService:
    global _prompt_loader
    if _prompt_loader is None:
        _prompt_loader = PromptLoaderService()
    return _prompt_loader


@dataclass
class PromptDisplay:
    """템플릿 표시용 프롬프트 데이터"""

    id: int
    type: str
    version: int
    content: str
    is_active: bool
    created_at: datetime
    created_by: int = 0


@router.get(
    "/prompts",
    response_class=HTMLResponse,
    summary="프롬프트 관리",
    description="프롬프트 관리 페이지"
)
async def admin_prompts(
    request: Request,
    current_admin: User = Depends(
        get_current_admin
    ),
):
    """프롬프트 관리 페이지"""
    logger.info(
        "프롬프트 관리 접근: "
        f"admin={current_admin.username}"
    )
    loader = _get_prompt_loader()
    prompt_types = loader.list_available_prompts()

    prompts = []
    for idx, ptype in enumerate(
        prompt_types, start=1
    ):
        content = loader.get_prompt(ptype)
        prompts.append(PromptDisplay(
            id=idx,
            type=ptype,
            version=1,
            content=content,
            is_active=True,
            created_at=datetime.now(),
        ))

    return templates.TemplateResponse(
        "admin/admin_prompts.html",
        {
            "request": request,
            "user": current_admin,
            "prompts": prompts,
        }
    )


@router.post(
    "/api/prompts",
    summary="프롬프트 생성",
)
async def create_prompt(
    request_data: SystemPromptCreateRequest,
    current_admin: User = Depends(
        get_current_admin
    ),
):
    """프롬프트 생성 API"""
    try:
        loader = _get_prompt_loader()
        loader.create_prompt(
            request_data.type,
            request_data.content,
        )
        logger.info(
            f"프롬프트 생성: type={request_data.type}, "
            f"admin={current_admin.username}"
        )
        return {
            "success": True,
            "message": "프롬프트가 생성되었습니다",
        }
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=str(e)
        )
    except (IOError, OSError) as e:
        logger.error(f"프롬프트 저장 실패: {e}")
        raise HTTPException(
            status_code=500,
            detail="프롬프트 파일 저장 중 오류 발생",
        )


@router.put(
    "/api/prompts/{prompt_type}",
    summary="프롬프트 수정",
)
async def update_prompt(
    prompt_type: str,
    request_data: SystemPromptUpdateRequest,
    current_admin: User = Depends(
        get_current_admin
    ),
):
    """프롬프트 수정 API"""
    try:
        loader = _get_prompt_loader()
        loader.update_prompt(
            prompt_type, request_data.content
        )
        logger.info(
            f"프롬프트 수정: type={prompt_type}, "
            f"admin={current_admin.username}"
        )
        return {
            "success": True,
            "message": "프롬프트가 수정되었습니다",
        }
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=str(e)
        )
    except (IOError, OSError) as e:
        logger.error(f"프롬프트 저장 실패: {e}")
        raise HTTPException(
            status_code=500,
            detail="프롬프트 파일 저장 중 오류 발생",
        )


@router.delete(
    "/api/prompts/{prompt_type}",
    summary="프롬프트 삭제",
)
async def delete_prompt_api(
    prompt_type: str,
    current_admin: User = Depends(
        get_current_admin
    ),
):
    """프롬프트 삭제 API"""
    try:
        loader = _get_prompt_loader()
        loader.delete_prompt(prompt_type)
        logger.info(
            f"프롬프트 삭제: type={prompt_type}, "
            f"admin={current_admin.username}"
        )
        return {
            "success": True,
            "message": "프롬프트가 삭제되었습니다",
        }
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=str(e)
        )
    except (IOError, OSError) as e:
        logger.error(f"프롬프트 저장 실패: {e}")
        raise HTTPException(
            status_code=500,
            detail="프롬프트 파일 저장 중 오류 발생",
        )
