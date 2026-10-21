"""관리자 export zip에 시뮬레이션 세션 jsonl 포함 (#160)."""

import io
import json
import zipfile

from app.schemas.admin_export import ExportFilters
from app.services.admin_export_service import AdminExportService

from .conftest import run


def _session_with_utterances(client, teacher, make_upload):
    make_upload(teacher)
    r = client.post(
        "/api/simulation/sessions",
        json={
            "random": {"n": 2, "grade": "all", "level": "all", "seed": 5},
            "phases": [{"name": "도입", "teacher_prompt": "발문"}],
        },
    )
    assert r.status_code == 201
    state = r.json()
    sid = state["session"]["id"]
    r = client.post(f"/api/simulation/sessions/{sid}/phases/0/enter")
    assert r.status_code == 200
    target = state["personas"][1]
    r = client.post(
        f"/api/simulation/sessions/{sid}/say",
        json={"content": "너는?", "target_persona_id": target["id"]},
    )
    assert r.status_code == 200
    return sid, target


def _zip(sim_db, filters):
    async def _go():
        async with sim_db() as db:
            svc = AdminExportService(db)
            plan = await svc.collect(filters)
            return b"".join(svc.stream_zip(plan))

    return zipfile.ZipFile(io.BytesIO(run(_go())))


def test_zip_contains_session_jsonl_in_seq_order(
    client, sim_db, teacher, make_upload, fake_gemini
):
    sid, target = _session_with_utterances(client, teacher, make_upload)
    zf = _zip(sim_db, ExportFilters())

    name = f"simulations/u{teacher.id:05d}__simsession_{sid}.jsonl"
    assert name in zf.namelist()
    lines = [json.loads(x) for x in zf.read(name).decode().splitlines()]
    # 입장: system, teacher, student x2 / 1:1 말하기: teacher, target student
    assert [x["seq"] for x in lines] == [1, 2, 3, 4, 5, 6]
    assert [x["speaker_type"] for x in lines] == [
        "system",
        "teacher",
        "student",
        "student",
        "teacher",
        "student",
    ]
    assert lines[4]["target_persona_id"] == target["id"]
    assert lines[5]["persona_name"] == target["display_name"]
    assert lines[5]["structured"]["ready_for_next"] is True
    assert set(lines[0]) == {
        "session_id",
        "seq",
        "phase_idx",
        "speaker_type",
        "persona_id",
        "persona_name",
        "target_persona_id",
        "content",
        "structured",
        "model_name",
        "latency_ms",
        "created_at",
    }
    readme = zf.read("README.txt").decode()
    assert "simulations/" in readme


def test_zip_excludes_simulations_without_conversations(
    client, sim_db, teacher, make_upload, fake_gemini
):
    _session_with_utterances(client, teacher, make_upload)
    zf = _zip(sim_db, ExportFilters(include=frozenset({"reports", "meta"})))
    assert not [n for n in zf.namelist() if n.startswith("simulations/")]


def test_zip_respects_user_filter(
    client, sim_db, teacher, other_teacher, make_upload, fake_gemini
):
    _session_with_utterances(client, teacher, make_upload)
    zf = _zip(sim_db, ExportFilters(user_ids=[other_teacher.id]))
    assert not [n for n in zf.namelist() if n.startswith("simulations/")]
