"""
내 학생 페르소나 라이브러리 API (목록·생성·삭제, 수정 없음)
"""

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.models.users import User
from app.schemas.simulation_library import CustomPersonaIn
from app.services.simulation import library
from app.services.simulation.errors import SimulationError

router = APIRouter(tags=["수업 시뮬레이션"])


@router.get("/api/simulation/library")
async def list_library(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items = await library.list_items(db, current_user.id)
    return {"items": [library.to_out(item) for item in items]}


@router.post("/api/simulation/library", status_code=201)
async def create_library_item(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 깨진 JSON·스키마 위반을 FastAPI 기본 422 대신 400으로 돌려준다
    try:
        profile = CustomPersonaIn.model_validate(await request.json())
    except (ValueError, ValidationError) as e:
        raise SimulationError("INVALID_PERSONA").to_http() from e
    try:
        item = await library.create(db, current_user.id, profile.model_dump())
    except SimulationError as e:
        raise e.to_http() from e
    return library.to_out(item)


@router.delete("/api/simulation/library/{item_id}", status_code=204)
async def delete_library_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await library.delete(db, current_user.id, item_id)
    except SimulationError as e:
        raise e.to_http() from e
    return Response(status_code=204)
