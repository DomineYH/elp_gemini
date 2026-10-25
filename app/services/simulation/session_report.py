"""
관리자용 세션 문서: 대화록 + 피드백 Markdown (#280)

관리자 다운로드와 일괄 내보내기가 같이 쓴다. DB 값만으로 만든다
(feedback_report_path 파일은 읽지 않는다).
"""

from app.services.simulation.feedback import render_markdown
from app.utils.text_sanitizer import strip_emojis
from app.utils.timestamps import utc_iso

STATUS_LABEL = {"setup": "준비", "running": "진행 중", "finished": "종료"}
NO_FEEDBACK = "피드백이 아직 생성되지 않았습니다."


def _clean(text) -> str:
    return strip_emojis(str(text)).strip()


def render_session_markdown(
    session, username, phases, personas, utterances
) -> str:
    """phases·personas·utterances는 ORM 객체 목록(utterances는 seq 순)."""
    # 국면·페르소나 이름도 모델이 만들 수 있어 이모지를 뺀다
    names = {p.id: _clean(p.display_name) for p in personas}
    phase_names = {p.idx: _clean(p.name) for p in phases}
    out = [
        f"# 수업 시뮬레이션 세션 {session.id}",
        "",
        f"- 세션: {session.id}",
        f"- 사용자: {username}",
        f"- 생성 시각: {utc_iso(session.created_at)}",
        f"- 종료 시각: {utc_iso(session.finished_at) or '-'}",
        f"- 상태: {STATUS_LABEL.get(session.status, session.status)}",
        f"- 페르소나 수: {session.persona_count}",
        f"- 모델: {session.model_name}",
        "",
        "## 페르소나",
        "",
    ]
    out += [
        f"- {names[p.id]} · {p.adapted_level} · {p.source}" for p in personas
    ]
    out += ["", "## 대화록"]

    # 화자 규칙은 관리자 로그 화면 loadDetail(JS)과 같다
    current = None
    for u in utterances:
        if u.phase_idx != current:
            current = u.phase_idx
            name = phase_names.get(current, f"국면 {current + 1}")
            out += ["", f"### {name}", ""]
        if u.speaker_type == "teacher":
            speaker = "교사"
        else:
            speaker = names.get(u.persona_id, "시스템")
        if u.target_persona_id:
            speaker += f" ({names.get(u.target_persona_id)}에게)"
        content = _clean(u.content).replace("\n", "\n  ")
        if u.speaker_type == "student" and u.structured is None:
            content = f"(파싱 실패) {content}"
        out.append(f"- **{speaker}**: {content}")

    out += ["", "## 피드백", ""]
    if session.feedback_json is None:
        out.append(NO_FEEDBACK)
    else:
        # 첫 두 줄(제목, 빈 줄)은 이 문서 제목과 겹치므로 뺀다
        body = render_markdown(
            session.feedback_json, session, [p.name for p in phases]
        ).splitlines()[2:]
        # 피드백 소제목을 한 단계 내려 "## 피드백" 아래에 둔다
        out += ["#" + line if line.startswith("#") else line for line in body]
    return "\n".join(out).rstrip() + "\n"
