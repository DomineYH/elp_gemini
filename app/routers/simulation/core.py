"""
수업 시뮬레이션 핵심 라우터: 설정 화면, 후보 페르소나, 세션 생성·진입·실행 화면
"""

import itertools
import random
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models.users import User
from app.schemas.simulation import (
    AdvanceRequest,
    AdvanceResult,
    CandidatesResponse,
    CreateSessionRequest,
    FinishResult,
    Level,
    RegenerateRequest,
    SayRequest,
    SessionList,
    SessionState,
    TurnResult,
)
from app.services.simulation import (
    lessonplan_source,
    library,
    persona_pool,
    phase_split,
    session_service,
)
from app.services.simulation.errors import SimulationError
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
    db: AsyncSession = Depends(get_db),
):
    if seed is None:
        seed = random.randrange(2**31)
    records = persona_pool.sample(
        persona_pool.load_pool(), grade, level, n, seed
    )
    names = persona_pool.assign_pseudonyms(len(records), seed)
    # 내 페르소나는 필터와 무관하게 전부, 표본에 안 쓰인 가명을 차례로 붙인다
    # ponytail: 라이브러리가 NAME_POOL보다 많아지면 가명이 반복된다.
    spare = itertools.cycle(
        [name for name in persona_pool.NAME_POOL if name not in names]
    )
    items = await library.list_items(db, current_user.id)
    return {
        "seed": seed,
        "candidates": [
            persona_pool.to_candidate(r, name)
            for r, name in zip(records, names)
        ]
        + [library.to_candidate(item, next(spare)) for item in items],
    }


@router.get("/api/simulation/phases/draft")
async def get_phase_draft(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 빈 행은 PhaseIn 검증(teacher_prompt 1자 이상)에 걸리므로 dict 그대로
    try:
        return await phase_split.draft_phases(db, current_user.id)
    except SimulationError as e:
        raise e.to_http() from e


@router.post(
    "/api/simulation/sessions",
    response_model=SessionState,
    status_code=201,
)
async def create_session(
    body: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await session_service.create_session(
            db, current_user.id, body
        )
    except SimulationError as e:
        raise e.to_http() from e
    return await session_service.load_state(db, session)


@router.get("/api/simulation/sessions/{sid}", response_model=SessionState)
async def get_session_state(
    sid: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await session_service.get_owned_session(
            db, sid, current_user.id
        )
    except SimulationError as e:
        raise e.to_http() from e
    return await session_service.load_state(db, session)


@router.post(
    "/api/simulation/sessions/{sid}/phases/{idx}/enter",
    response_model=TurnResult,
)
async def enter_phase(
    sid: int,
    idx: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await session_service.get_owned_session(
            db, sid, current_user.id
        )
        return await session_service.enter_phase(db, session, idx)
    except SimulationError as e:
        raise e.to_http() from e


@router.post("/api/simulation/sessions/{sid}/say", response_model=TurnResult)
async def say(
    sid: int,
    body: SayRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await session_service.get_owned_session(
            db, sid, current_user.id
        )
        return await session_service.say(db, session, body)
    except SimulationError as e:
        raise e.to_http() from e


@router.post(
    "/api/simulation/sessions/{sid}/advance", response_model=AdvanceResult
)
async def advance(
    sid: int,
    body: AdvanceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await session_service.get_owned_session(
            db, sid, current_user.id
        )
        return await session_service.advance(db, session, body.mode)
    except SimulationError as e:
        raise e.to_http() from e


@router.post(
    "/api/simulation/sessions/{sid}/finish", response_model=FinishResult
)
async def finish(
    sid: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await session_service.get_owned_session(
            db, sid, current_user.id
        )
        return await session_service.finish(db, session)
    except SimulationError as e:
        raise e.to_http() from e


@router.post(
    "/api/simulation/sessions/{sid}/regenerate", response_model=TurnResult
)
async def regenerate(
    sid: int,
    body: RegenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await session_service.get_owned_session(
            db, sid, current_user.id
        )
        return await session_service.regenerate(db, session, body.persona_id)
    except SimulationError as e:
        raise e.to_http() from e


@router.get("/simulation/sessions/{sid}", response_class=HTMLResponse)
async def simulation_run_page(
    sid: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await session_service.get_owned_session(
            db, sid, current_user.id
        )
    except SimulationError:
        raise HTTPException(
            status_code=404, detail="시뮬레이션 세션을 찾을 수 없습니다."
        )
    return templates.TemplateResponse(
        "user/simulation.html",
        {
            "request": request,
            "user": current_user,
            "sid": session.id,
            "persona_count": session.persona_count,
        },
    )


@router.get("/api/simulation/sessions", response_model=SessionList)
async def list_sessions(
    upload_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {
        "sessions": await session_service.list_sessions(
            db, current_user.id, upload_id
        )
    }
