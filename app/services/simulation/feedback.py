"""
시뮬레이션 피드백(가설): 입력 조립, 생성·캐시, Markdown 보고서 (PLAN 2.6)

생성은 세션당 한 번. feedback_json이 있으면 Gemini를 부르지 않는다.
"""

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.simulation_session import SimulationSession
from app.services.report_storage_service import ReportStorageService
from app.services.simulation import (
    gemini,
    guidelines,
    lessonplan_source,
    session_service,
)
from app.services.simulation.errors import SimulationError
from app.services.simulation.llm_schemas import FeedbackResult
from app.utils.text_sanitizer import strip_emojis

REPORTS_DIR = "app/static/reports"
TITLE = "# 수업 시뮬레이션 피드백(가설)"
DISCLAIMER = (
    "이 보고서는 학생 프로필을 조건으로 생성형 AI가 만든 시뮬레이션 반응에서 "
    "도출한 가설입니다. 실제 학생의 행동을 예측하거나 진단하지 않으며, "
    "지도안을 점검하는 참고 자료로만 사용하세요."
)
# 스토리 42: 섹션마다 붙이는 고정 안내
SECTION_NOTE = "이 섹션의 내용은 시뮬레이션에서 나온 가설이며 예측이 아닙니다."
TRANSITIONS = {
    "agree_advance": "전원 동의 후 전이",
    "skip": "교사 개입 전 전이(Skip)",
    "end": "수업 종료",
}


async def build_inputs(db: AsyncSession, session: SimulationSession) -> str:
    """지도안 전문 + 국면 + 페르소나 요약 + 전이 이력 + 대화록(seq 순)."""
    sid = session.id
    upload = await db.get(LessonPlanUpload, session.upload_id)
    phases = await session_service._phases(db, sid)
    personas = await session_service._personas(db, sid)
    utterances = await session_service._utterances(db, sid)
    names = {p.id: p.display_name for p in personas}
    phase_name = {p.idx: p.name for p in phases}

    lines = ["[지도안 전문]", lessonplan_source.extract_text(upload), ""]
    lines.append("[국면]")
    for p in phases:
        minutes = f" ({p.minutes}분)" if p.minutes else ""
        lines.append(f"{p.idx + 1}. {p.name}{minutes}")
        for label, value in (
            ("지도안 발문", p.teacher_prompt),
            ("과업", p.task),
            ("자료", p.materials),
            ("유의점", p.cautions),
        ):
            if value:
                lines.append(f"   - {label}: {value}")

    lines += ["", "[학생 페르소나]"]
    for p in personas:
        profile = p.adapted_profile
        lines.append(
            f"- {p.display_name} ({p.adapted_level}): "
            f"{profile.get('behavior_summary', '')} "
            f"/ 강점: {', '.join(profile.get('strengths', []))} "
            f"/ 약점: {', '.join(profile.get('weaknesses', []))} "
            f"/ 지원 요구: {profile.get('support_needs', '')}"
        )

    lines += ["", "[국면 전이 이력]"]
    for u in utterances:
        kind = (u.structured or {}).get("type")
        if u.speaker_type == "system" and kind in TRANSITIONS:
            lines.append(
                f"- {phase_name.get(u.phase_idx, u.phase_idx)}: "
                f"{TRANSITIONS[kind]}"
            )

    lines += ["", "[대화록]"]
    for u in utterances:
        if u.speaker_type == "system":
            continue
        if u.speaker_type == "teacher":
            to = names.get(u.target_persona_id)
            speaker = f"교사({to + '에게' if to else '전체'})"
            content = u.content
        else:
            speaker = names[u.persona_id]
            content = (
                session_service.student_evidence(u)
                if u.structured
                else "(반응 생성 실패)"
            )
        lines.append(
            f"[{phase_name.get(u.phase_idx, u.phase_idx)}] {speaker}: {content}"
        )
    return "\n".join(lines)


def _guideline_label(version: int | None) -> str:
    return f"커스텀 v{version}" if version else "기본값"


def render_markdown(
    envelope: dict,
    session: SimulationSession,
    phase_names: list[str] | None = None,
) -> str:
    """모델이 쓴 글은 모두 strip_emojis를 거친다."""
    fb = envelope["feedback"]
    names = phase_names or []

    def clean(text) -> str:
        return strip_emojis(str(text)).strip()

    def phase_label(idx: int) -> str:
        return names[idx] if 0 <= idx < len(names) else f"국면 {idx + 1}"

    out = [
        TITLE,
        "",
        DISCLAIMER,
        "",
        f"- 세션: {session.id}",
        f"- 모델: {envelope['model_name']} · 응답 "
        f"{envelope['latency_ms'] / 1000:.1f}s · 적용 지침: "
        f"{_guideline_label(envelope.get('guideline_version'))}",
        f"- 생성 시각: {envelope['created_at']}",
        "",
        "## 위험 시나리오",
        "",
        SECTION_NOTE,
        "",
    ]
    for i, r in enumerate(fb["risk_scenarios"], 1):
        out += [
            f"### R{i}. {clean(r['title'])}",
            "",
            clean(r["scene"]),
            "",
            f"- 근거 유형: {clean(r['evidence_type'])}",
            "",
        ]

    out += ["## ① 교사 발화 추천", "", SECTION_NOTE, ""]
    for s in fb["utterance_suggestions"]:
        out += [
            f"### {clean(phase_label(s['phase_idx']))}",
            "",
            f"- 실제 발화: {clean(s['actual'])}",
            f"- 추천 발화: {clean(s['suggested'])}",
            f"- 의도: {clean(s['intent'])}",
            "",
        ]

    out += ["## ② 진행 방향", "", SECTION_NOTE, ""]
    out += [f"- {clean(d)}" for d in fb["progress_directions"]]
    out += ["", "## ③ 변경 방향", "", SECTION_NOTE, ""]
    out += [
        f"- **{clean(c['kind'])}** {clean(c['content'])}"
        for c in fb["change_directions"]
    ]
    return "\n".join(out) + "\n"


async def call_model(db: AsyncSession, session: SimulationSession, system: str):
    """피드백 1회 호출(저장 없음). 파싱 실패 → FEEDBACK_PARSE_FAILED."""
    user = await build_inputs(db, session)
    [result] = await gemini.call_many(
        [
            {
                "kind": "feedback",
                "system": system,
                "user": user,
                "schema": FeedbackResult,
            }
        ]
    )
    if result.parsed is None:
        raise SimulationError("FEEDBACK_PARSE_FAILED")
    return result


async def generate(db: AsyncSession, session: SimulationSession) -> dict:
    """envelope + cached. 미종료 → SESSION_NOT_FINISHED."""
    if session.status != "finished":
        raise SimulationError("SESSION_NOT_FINISHED")
    if session.feedback_json is not None:
        return {**session.feedback_json, "cached": True}

    guideline = await guidelines.current(db)
    # 지침이 꺼져 있으면 기본값(null)으로 기록한다
    version = guideline.version if guideline and guideline.enabled else None
    result = await call_model(
        db, session, await guidelines.system_prompt(db, guideline)
    )

    envelope = {
        "feedback": result.parsed.model_dump(),
        "model_name": result.model,
        "latency_ms": result.latency_ms,
        "guideline_version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    phases = await session_service._phases(db, session.id)
    md = render_markdown(envelope, session, [p.name for p in phases])
    saved = ReportStorageService(base_dir=REPORTS_DIR).save_report(
        session.user_id, f"simulation_{session.id}.md", md
    )
    # 동시 생성: 먼저 저장한 쪽만 남기고 이쪽 파일은 지운다
    written = await db.execute(
        update(SimulationSession)
        .where(
            SimulationSession.id == session.id,
            SimulationSession.feedback_json.is_(None),
        )
        .values(
            feedback_json=envelope,
            feedback_guideline_version=version,
            feedback_report_path=saved["file_path"],
        )
    )
    await db.commit()
    if written.rowcount == 0:
        Path(saved["file_path"]).unlink(missing_ok=True)
        await db.refresh(session)
        return {**session.feedback_json, "cached": True}
    return {**envelope, "cached": False}
