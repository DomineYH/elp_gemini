"""
시뮬레이션 세션: 생성, 국면 진입, 말하기, 전이, 종료, 상태 조회 (PLAN 2.6)

Gemini 호출이 모두 끝난 뒤에만 DB에 쓴다(실패 시 아무것도 남기지 않음).
"""

import json
import random
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.simulation_persona import SimulationPersona
from app.models.simulation_phase import SimulationPhase
from app.models.simulation_session import SimulationSession
from app.models.simulation_utterance import SimulationUtterance
from app.schemas.simulation import CreateSessionRequest, Persona, SayRequest
from app.services.prompt_loader_service import PromptLoaderService
from app.services.simulation import gemini, lessonplan_source, persona_pool
from app.services.simulation.adaptation import adapt_many
from app.services.simulation.agreement import compute_agreement
from app.services.simulation.errors import SimulationError
from app.services.simulation.llm_schemas import StudentReaction

PHASE_FIELDS = (
    "name",
    "minutes",
    "teacher_prompt",
    "task",
    "materials",
    "cautions",
    "source_span",
)


async def get_owned_session(
    db: AsyncSession, sid: int, user_id: int
) -> SimulationSession:
    """없거나 남의 세션 → SESSION_NOT_FOUND (403이 아니라 404)."""
    session = await db.scalar(
        select(SimulationSession).where(
            SimulationSession.id == sid,
            SimulationSession.user_id == user_id,
        )
    )
    if session is None:
        raise SimulationError("SESSION_NOT_FOUND")
    return session


async def create_session(
    db: AsyncSession, user_id: int, body: CreateSessionRequest
) -> SimulationSession:
    upload = await lessonplan_source.get_latest_upload(db, user_id)
    if upload is None:
        raise SimulationError("NO_UPLOAD")

    # 페르소나 결정 (#158이 custom: ref 처리를 이 블록에 넣는다)
    if body.personas is not None:
        refs = [p.ref for p in body.personas]
        names = [p.pseudonym for p in body.personas]
        if len(set(names)) != len(names) or any(
            n not in persona_pool.NAME_POOL for n in names
        ):
            raise SimulationError("DUPLICATE_PSEUDONYM")
        raws = persona_pool.resolve_refs(refs)
    else:
        pick = body.random
        seed = pick.seed if pick.seed is not None else random.randrange(2**31)
        raws = persona_pool.sample(
            persona_pool.load_pool(), pick.grade, pick.level, pick.n, seed
        )
        names = persona_pool.assign_pseudonyms(len(raws), seed)
        refs = [str(r["id"]) for r in raws]
    adapted = await adapt_many(list(zip(refs, raws)))
    seats = [
        {
            "source": "dataset",
            "source_record_id": raw["id"],
            "raw_profile": raw,
        }
        for raw in raws
    ]

    session = SimulationSession(
        user_id=user_id,
        upload_id=upload.id,
        status="running",
        current_phase_idx=0,
        persona_count=len(seats),
        model_name=settings.GEMINI_SIM_MODEL,
    )
    db.add(session)
    await db.flush()
    for idx, phase in enumerate(body.phases):
        db.add(
            SimulationPhase(
                session_id=session.id, idx=idx, **phase.model_dump()
            )
        )
    for seat_idx, (seat, name, (profile, level)) in enumerate(
        zip(seats, names, adapted)
    ):
        db.add(
            SimulationPersona(
                session_id=session.id,
                seat_idx=seat_idx,
                display_name=name,
                color_key=f"p{seat_idx + 1}",
                adapted_profile=profile,
                adapted_level=level,
                **seat,
            )
        )
    await db.commit()
    await db.refresh(session)
    return session


async def _phases(db, sid):
    return list(
        await db.scalars(
            select(SimulationPhase)
            .where(SimulationPhase.session_id == sid)
            .order_by(SimulationPhase.idx)
        )
    )


async def _personas(db, sid):
    return list(
        await db.scalars(
            select(SimulationPersona)
            .where(SimulationPersona.session_id == sid)
            .order_by(SimulationPersona.seat_idx)
        )
    )


async def _utterances(db, sid, phase_idx=None):
    query = select(SimulationUtterance).where(
        SimulationUtterance.session_id == sid
    )
    if phase_idx is not None:
        query = query.where(SimulationUtterance.phase_idx == phase_idx)
    return list(await db.scalars(query.order_by(SimulationUtterance.seq)))


def _utterance_out(u: SimulationUtterance) -> dict:
    return {
        "id": u.id,
        "seq": u.seq,
        "phase_idx": u.phase_idx,
        "speaker_type": u.speaker_type,
        "persona_id": u.persona_id,
        "target_persona_id": u.target_persona_id,
        "content": u.content,
        "structured": u.structured,
        "failed": u.speaker_type == "student" and u.structured is None,
        "model_name": u.model_name,
        "latency_ms": u.latency_ms,
        "created_at": u.created_at,
    }


async def _teacher_turns_used(db, sid) -> int:
    teacher = await db.scalars(
        select(SimulationUtterance.structured).where(
            SimulationUtterance.session_id == sid,
            SimulationUtterance.speaker_type == "teacher",
        )
    )
    return sum(1 for s in teacher if (s or {}).get("source") == "user")


async def _agreement(db, sid) -> dict:
    """현재 국면의 동의 상태."""
    idx = (await db.get(SimulationSession, sid)).current_phase_idx
    return compute_agreement(
        idx, await _personas(db, sid), await _utterances(db, sid, idx)
    )


async def _turn_result(db, sid, utterances) -> dict:
    return {
        "utterances": [_utterance_out(u) for u in utterances],
        "failed_persona_ids": [
            u.persona_id
            for u in utterances
            if u.speaker_type == "student" and u.structured is None
        ],
        "agreement": await _agreement(db, sid),
        "teacher_turns_used": await _teacher_turns_used(db, sid),
    }


def student_call(persona: SimulationPersona, phase, transcript: list[str]):
    """학생 반응 1건의 call_structured 인자. transcript = 이번 국면 대화 줄."""
    profile = {
        "가명": persona.display_name,
        "학년": persona.raw_profile.get("grade"),
        "학업 수준": persona.adapted_level,
        **persona.adapted_profile,
    }
    system = (
        PromptLoaderService().get_prompt("sim_student")
        + "\n\n[나의 프로필]\n"
        + json.dumps(profile, ensure_ascii=False)
    )
    user = "\n".join(
        [
            f"[현재 국면] {phase.name}"
            + (f" ({phase.minutes}분)" if phase.minutes else ""),
            f"과업: {phase.task or '(없음)'}",
            f"자료: {phase.materials or '(없음)'}",
            "",
            "[이번 국면 대화]",
            *transcript,
        ]
    )
    return {
        "kind": "student",
        "system": system,
        "user": user,
        "schema": StudentReaction,
        "persona_key": (
            f"custom:{persona.source_record_id}"
            if persona.source == "custom"
            else str(persona.source_record_id)
        ),
    }


def student_utterance(
    session_id: int,
    phase_idx: int,
    seq: int,
    persona: SimulationPersona,
    result: gemini.LLMResult,
) -> SimulationUtterance:
    """파싱 실패면 structured=NULL, content=모델 원문."""
    reaction = result.parsed
    return SimulationUtterance(
        session_id=session_id,
        phase_idx=phase_idx,
        seq=seq,
        speaker_type="student",
        persona_id=persona.id,
        content=(
            (reaction.utterance or f"({reaction.action})")
            if reaction
            else result.text
        ),
        structured=reaction.model_dump() if reaction else None,
        model_name=result.model,
        temperature=result.temperature,
        latency_ms=result.latency_ms,
    )


async def next_seq(db, sid) -> int:
    current = await db.scalar(
        select(func.max(SimulationUtterance.seq)).where(
            SimulationUtterance.session_id == sid
        )
    )
    return (current or 0) + 1


async def enter_phase(
    db: AsyncSession, session: SimulationSession, idx: int
) -> dict:
    """phase_enter → 교사(지도안 발문) → 학생 반응(좌석 순).

    이미 들어온 국면이면 저장본을 돌려준다.
    """
    if session.status == "finished":
        raise SimulationError("SESSION_FINISHED")
    if idx != session.current_phase_idx:
        raise SimulationError("PHASE_NOT_CURRENT")
    stored = await _utterances(db, session.id, idx)
    if stored:
        return await _turn_result(db, session.id, stored)

    phase = (await _phases(db, session.id))[idx]
    personas = await _personas(db, session.id)
    transcript = [f"교사(전체): {phase.teacher_prompt}"]
    results = await gemini.call_many(
        [student_call(p, phase, transcript) for p in personas]
    )

    seq = await next_seq(db, session.id)
    rows = [
        SimulationUtterance(
            session_id=session.id,
            phase_idx=idx,
            seq=seq,
            speaker_type="system",
            content=f"{phase.name} 국면 시작",
            structured={"type": "phase_enter"},
        ),
        SimulationUtterance(
            session_id=session.id,
            phase_idx=idx,
            seq=seq + 1,
            speaker_type="teacher",
            content=phase.teacher_prompt,
            structured={"source": "plan"},
        ),
    ]
    rows += [
        student_utterance(session.id, idx, seq + 2 + i, p, r)
        for i, (p, r) in enumerate(zip(personas, results))
    ]
    db.add_all(rows)
    try:
        await db.commit()
    except IntegrityError:
        # 동시 진입: 먼저 쓴 쪽의 저장본을 돌려준다
        await db.rollback()
    stored = await _utterances(db, session.id, idx)
    return await _turn_result(db, session.id, stored)


async def load_state(db: AsyncSession, session: SimulationSession) -> dict:
    sid = session.id
    return {
        "session": {
            "id": sid,
            "status": session.status,
            "current_phase_idx": session.current_phase_idx,
            "persona_count": session.persona_count,
            "model_name": session.model_name,
            "upload_id": session.upload_id,
            "created_at": session.created_at,
            "finished_at": session.finished_at,
            "teacher_turns_used": await _teacher_turns_used(db, sid),
            "teacher_turns_max": settings.SIM_MAX_TEACHER_TURNS,
            "has_feedback": session.feedback_json is not None,
        },
        "phases": [
            {"idx": p.idx, **{f: getattr(p, f) for f in PHASE_FIELDS}}
            for p in await _phases(db, sid)
        ],
        "personas": [
            {f: getattr(p, f) for f in Persona.model_fields}
            for p in await _personas(db, sid)
        ],
        "utterances": [_utterance_out(u) for u in await _utterances(db, sid)],
        "agreement": await _agreement(db, sid),
    }


def _transcript_line(u: SimulationUtterance, names: dict) -> str:
    if u.speaker_type == "teacher":
        to = names.get(u.target_persona_id)
        return f"교사({to + '에게' if to else '전체'}): {u.content}"
    return f"{names[u.persona_id]}: {u.content}"


async def _commit_or_conflict(db) -> None:
    """seq 유니크 충돌 = 동시 요청 → 아무것도 남기지 않고 CONFLICT_RETRY."""
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise SimulationError("CONFLICT_RETRY")


async def say(
    db: AsyncSession, session: SimulationSession, body: SayRequest
) -> dict:
    """교사 발화(source=user) → 대상 학생(없으면 전원) 반응."""
    if session.status == "finished":
        raise SimulationError("SESSION_FINISHED")
    sid, idx = session.id, session.current_phase_idx
    stored = await _utterances(db, sid, idx)
    if not stored:
        raise SimulationError("PHASE_NOT_ENTERED")
    personas = await _personas(db, sid)
    target = body.target_persona_id
    if target is not None and target not in {p.id for p in personas}:
        raise SimulationError("UNKNOWN_PERSONA")

    teacher = SimulationUtterance(
        session_id=sid,
        phase_idx=idx,
        speaker_type="teacher",
        target_persona_id=target,
        content=body.content,
        structured={"source": "user"},
    )
    names = {p.id: p.display_name for p in personas}
    transcript = [
        _transcript_line(u, names)
        for u in stored + [teacher]
        if u.speaker_type != "system"
    ]
    phase = (await _phases(db, sid))[idx]
    responders = [p for p in personas if target in (None, p.id)]
    results = await gemini.call_many(
        [student_call(p, phase, transcript) for p in responders]
    )

    seq = await next_seq(db, sid)
    teacher.seq = seq
    db.add(teacher)
    db.add_all(
        student_utterance(sid, idx, seq + 1 + i, p, r)
        for i, (p, r) in enumerate(zip(responders, results))
    )
    await _commit_or_conflict(db)
    new = [u for u in await _utterances(db, sid, idx) if u.seq >= seq]
    return await _turn_result(db, sid, new)


def _system(session, seq, content, structured) -> SimulationUtterance:
    return SimulationUtterance(
        session_id=session.id,
        phase_idx=session.current_phase_idx,
        seq=seq,
        speaker_type="system",
        content=content,
        structured=structured,
    )


def _finish_now(session) -> None:
    session.status = "finished"
    # CURRENT_TIMESTAMP(created_at)와 같은 UTC naive
    session.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)


async def advance(db: AsyncSession, session: SimulationSession, mode) -> dict:
    """agree(전원 동의일 때만) / skip(항상). 마지막 국면이면 종료."""
    if session.status == "finished":
        raise SimulationError("SESSION_FINISHED")
    if mode == "agree" and not (await _agreement(db, session.id))["all_agreed"]:
        raise SimulationError("NOT_ALL_AGREED")
    phases = await _phases(db, session.id)
    phase = phases[session.current_phase_idx]
    seq = await next_seq(db, session.id)
    if mode == "agree":
        rows = [
            _system(
                session,
                seq,
                f"{phase.name}: 전원 동의로 다음 국면",
                {"type": "agree_advance"},
            )
        ]
    else:
        rows = [
            _system(session, seq, f"{phase.name}: 건너뜀", {"type": "skip"})
        ]
    next_phase = None
    if session.current_phase_idx + 1 < len(phases):
        session.current_phase_idx += 1
        p = phases[session.current_phase_idx]
        next_phase = {"idx": p.idx, **{f: getattr(p, f) for f in PHASE_FIELDS}}
    else:
        rows.append(
            _system(
                session,
                seq + 1,
                "수업 종료 (마지막 국면)",
                {"type": "end", "reason": "last_phase"},
            )
        )
        _finish_now(session)
    db.add_all(rows)
    await _commit_or_conflict(db)
    return {
        "status": session.status,
        "current_phase_idx": session.current_phase_idx,
        "next_phase": next_phase,
    }


async def finish(db: AsyncSession, session: SimulationSession) -> dict:
    """수업 종료 버튼: 시스템 end(finish) + finished."""
    if session.status == "finished":
        raise SimulationError("SESSION_FINISHED")
    seq = await next_seq(db, session.id)
    db.add(
        _system(session, seq, "수업 종료", {"type": "end", "reason": "finish"})
    )
    _finish_now(session)
    await _commit_or_conflict(db)
    return {"status": "finished"}
