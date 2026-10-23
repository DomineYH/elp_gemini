"""
시뮬레이션 세션: 생성, 국면 진입, 말하기, 전이, 종료, 상태 조회 (PLAN 2.6)

Gemini 호출이 모두 끝난 뒤에만 DB에 쓴다(실패 시 아무것도 남기지 않음).
"""

import json
import random
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.simulation_persona import SimulationPersona
from app.models.simulation_phase import SimulationPhase
from app.models.simulation_session import SimulationSession
from app.models.simulation_utterance import SimulationUtterance
from app.schemas.simulation import CreateSessionRequest, Persona, SayRequest
from app.services.prompt_loader_service import PromptLoaderService
from app.services.simulation import (
    gemini,
    lessonplan_source,
    library,
    persona_pool,
)
from app.services.simulation.adaptation import adapt_many
from app.services.simulation.agreement import compute_agreement
from app.services.simulation.errors import SimulationError
from app.services.simulation.llm_schemas import StudentReaction
from app.utils.timestamps import utc_iso

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
    limit = await persona_pool.effective_max_personas(db)
    requested = (
        len(body.personas) if body.personas is not None else body.random.n
    )
    if requested > limit:
        raise SimulationError("TOO_MANY_PERSONAS")

    # 페르소나 결정: custom:<id>는 라이브러리 번안본을 복사, 데이터셋만 번안
    custom = {}
    if body.personas is not None:
        refs = [p.ref for p in body.personas]
        names = [p.pseudonym for p in body.personas]
        if len(set(names)) != len(names) or any(
            n not in persona_pool.NAME_POOL for n in names
        ):
            raise SimulationError("DUPLICATE_PSEUDONYM")
        custom_refs = [r for r in refs if r.startswith("custom:")]
        ids = [r.removeprefix("custom:") for r in custom_refs]
        # "custom:01"처럼 같은 항목을 다른 철자로 두 번 앉히지 못하게 한다
        if not all(i.isdecimal() and str(int(i)) == i for i in ids):
            raise SimulationError("UNKNOWN_PERSONA")
        items = await library.snapshot_for_session(
            db, user_id, [int(i) for i in ids]
        )
        custom = dict(zip(custom_refs, items))
        dataset_refs = [r for r in refs if r not in custom]
        by_ref = dict(
            zip(dataset_refs, persona_pool.resolve_refs(dataset_refs))
        )
    else:
        pick = body.random
        seed = pick.seed if pick.seed is not None else random.randrange(2**31)
        raws = persona_pool.sample(
            persona_pool.load_pool(), pick.grade, pick.level, pick.n, seed
        )
        names = persona_pool.assign_pseudonyms(len(raws), seed)
        refs = [str(r["id"]) for r in raws]
        by_ref = dict(zip(refs, raws))
    adapted_by_ref = dict(zip(by_ref, await adapt_many(list(by_ref.items()))))
    seats, adapted = [], []
    for ref in refs:
        if ref in custom:
            item = custom[ref]
            seats.append(
                {
                    "source": "custom",
                    "source_record_id": item.id,
                    "raw_profile": item.raw_profile,
                }
            )
            adapted.append((item.adapted_profile, item.adapted_level))
        else:
            seats.append(
                {
                    "source": "dataset",
                    "source_record_id": by_ref[ref]["id"],
                    "raw_profile": by_ref[ref],
                }
            )
            adapted.append(adapted_by_ref[ref])

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
        "created_at": utc_iso(u.created_at),
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
    await _lock_running(db, session, idx, moved="PHASE_NOT_CURRENT")
    stored = await _utterances(db, session.id, idx)
    if stored:
        result = await _turn_result(db, session.id, stored)
        await db.rollback()  # 잠금만 풀고 아무것도 쓰지 않는다
        return result

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
    latest = await lessonplan_source.get_latest_upload(db, session.user_id)
    return {
        "session": {
            "id": sid,
            "status": session.status,
            "current_phase_idx": session.current_phase_idx,
            "persona_count": session.persona_count,
            "model_name": session.model_name,
            "upload_id": session.upload_id,
            "created_at": utc_iso(session.created_at),
            "finished_at": utc_iso(session.finished_at),
            "teacher_turns_used": await _teacher_turns_used(db, sid),
            "teacher_turns_max": settings.SIM_MAX_TEACHER_TURNS,
            "has_feedback": session.feedback_json is not None,
            "is_latest_upload": latest is not None
            and latest.id == session.upload_id,
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
    # 오개념 태그를 보이면 학생 모델이 남의·이전 오개념을 옮겨 적는다 (#274)
    return f"{names[u.persona_id]}: {student_evidence(u, misconception=False)}"


def student_evidence(u: SimulationUtterance, misconception: bool = True) -> str:
    """모델용 대화록: 발화 + 비어 있지 않은 산출물·오개념. 실패 반응은 원문."""
    s = u.structured or {}
    fields = [("artifact", "산출물")]
    if misconception:
        fields.append(("misconception", "오개념"))
    tags = [f"[{label}: {s[key]}]" for key, label in fields if s.get(key)]
    return " ".join([u.content, *tags])


async def _commit_or_conflict(db) -> None:
    """seq 유니크 충돌 = 동시 요청 → 아무것도 남기지 않고 CONFLICT_RETRY."""
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise SimulationError("CONFLICT_RETRY")


async def _lock_running(
    db, session: SimulationSession, idx: int, moved="CONFLICT_RETRY"
) -> None:
    """쓰기 잠금을 잡은 채 진행 중·같은 국면인지 확인한다.

    잠금은 이 요청의 커밋·롤백까지 유지되므로 그 사이 다른 요청의 종료·전이·
    발화가 끼어들 수 없다. 이미 바뀌었으면 아무것도 쓰지 않는다.
    """
    locked = await db.execute(
        update(SimulationSession)
        .where(
            SimulationSession.id == session.id,
            SimulationSession.status == "running",
            SimulationSession.current_phase_idx == idx,
        )
        .values(current_phase_idx=SimulationSession.current_phase_idx)
        .execution_options(synchronize_session=False)
    )
    if locked.rowcount:
        return
    await db.rollback()
    await db.refresh(session)
    if session.status == "finished":
        raise SimulationError("SESSION_FINISHED")
    raise SimulationError(moved)


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
    if await _teacher_turns_used(db, sid) >= settings.SIM_MAX_TEACHER_TURNS:
        raise SimulationError("TURN_LIMIT")

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
    await _lock_running(db, session, idx)
    if await _teacher_turns_used(db, sid) >= settings.SIM_MAX_TEACHER_TURNS:
        await db.rollback()
        raise SimulationError("TURN_LIMIT")

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
    await _lock_running(db, session, session.current_phase_idx)
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
    await _lock_running(db, session, session.current_phase_idx)
    seq = await next_seq(db, session.id)
    db.add(
        _system(session, seq, "수업 종료", {"type": "end", "reason": "finish"})
    )
    _finish_now(session)
    await _commit_or_conflict(db)
    return {"status": "finished"}


async def regenerate(
    db: AsyncSession, session: SimulationSession, persona_id: int
) -> dict:
    """현재 국면에서 파싱 실패한 마지막 반응을 같은 맥락으로 다시 만든다.

    그 행을 그대로 고친다(seq 유지, 교사 발화 없음, 발화 수 미포함).
    """
    if session.status == "finished":
        raise SimulationError("SESSION_FINISHED")
    sid, idx = session.id, session.current_phase_idx
    personas = await _personas(db, sid)
    if persona_id not in {p.id for p in personas}:
        raise SimulationError("UNKNOWN_PERSONA")
    stored = await _utterances(db, sid, idx)
    mine = [u for u in stored if u.persona_id == persona_id]
    if not mine or mine[-1].structured is not None:
        raise SimulationError("NOTHING_TO_REGENERATE")
    row = mine[-1]
    # 원래 호출의 맥락 = 그 반응을 부른 교사 발화까지
    asked = max(
        u.seq for u in stored if u.speaker_type == "teacher" and u.seq < row.seq
    )
    names = {p.id: p.display_name for p in personas}
    transcript = [
        _transcript_line(u, names)
        for u in stored
        if u.speaker_type != "system" and u.seq <= asked
    ]
    persona = next(p for p in personas if p.id == persona_id)
    phase = (await _phases(db, sid))[idx]
    [result] = await gemini.call_many(
        [student_call(persona, phase, transcript)]
    )
    await _lock_running(db, session, idx)

    fresh = student_utterance(sid, idx, row.seq, persona, result)
    for field in (
        "content",
        "structured",
        "model_name",
        "temperature",
        "latency_ms",
    ):
        setattr(row, field, getattr(fresh, field))
    await db.commit()
    await db.refresh(row)
    return await _turn_result(db, sid, [row])


async def list_sessions(
    db: AsyncSession, user_id: int, upload_id: int | None = None
) -> list[dict]:
    """내 세션만, 최신 먼저 (phase_split 승계와 같은 정렬)."""
    phase_count = (
        select(func.count(SimulationPhase.id))
        .where(SimulationPhase.session_id == SimulationSession.id)
        .scalar_subquery()
    )
    query = select(SimulationSession, phase_count).where(
        SimulationSession.user_id == user_id
    )
    if upload_id is not None:
        query = query.where(SimulationSession.upload_id == upload_id)
    rows = await db.execute(
        query.order_by(
            SimulationSession.created_at.desc(), SimulationSession.id.desc()
        )
    )
    return [
        {
            "id": s.id,
            "created_at": utc_iso(s.created_at),
            "persona_count": s.persona_count,
            "status": s.status,
            "has_feedback": s.feedback_json is not None,
            "upload_id": s.upload_id,
            "current_phase_idx": s.current_phase_idx,
            "phase_count": count,
        }
        for s, count in rows
    ]
