"""
수업 시뮬레이션 핵심 라우터: 설정 화면, 후보 페르소나
"""

import random
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models.users import User
from app.schemas.simulation import CandidatesResponse, Level
from app.services.simulation import lessonplan_source, persona_pool
from app.templating import templates

router = APIRouter(tags=["수업 시뮬레이션"])

PLAN_SUMMARY_CHARS = 300


@router.get("/simulation/setup", response_class=HTMLResponse)
async def simulation_setup_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    upload = await lessonplan_source.get_latest_upload(db, current_user.id)
    summary = (
        lessonplan_source.extract_text(upload)[:PLAN_SUMMARY_CHARS]
        if upload
        else ""
    )
    return templates.TemplateResponse(
        "user/simulation_setup.html",
        {
            "request": request,
            "user": current_user,
            "upload": upload,
            "plan_summary": summary,
            "min_personas": persona_pool.MIN_PERSONAS,
            "max_personas": settings.SIM_MAX_PERSONAS,
            "level_labels": persona_pool.LEVEL_LABELS,
        },
    )


@router.get("/api/simulation/candidates", response_model=CandidatesResponse)
async def get_candidates(
    grade: Literal["all", "5", "6"] = "all",
    level: Literal["all"] | Level = "all",
    n: int = Query(
        4, ge=persona_pool.MIN_PERSONAS, le=settings.SIM_MAX_PERSONAS
    ),
    seed: int | None = None,
    current_user: User = Depends(get_current_user),
):
    if seed is None:
        seed = random.randrange(2**31)
    records = persona_pool.sample(
        persona_pool.load_pool(), grade, level, n, seed
    )
    names = persona_pool.assign_pseudonyms(len(records), seed)
    return {
        "seed": seed,
        "candidates": [
            persona_pool.to_candidate(r, name)
            for r, name in zip(records, names)
        ],
    }
