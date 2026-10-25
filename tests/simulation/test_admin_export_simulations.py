"""관리자 export zip에 시뮬레이션 세션 jsonl·md 포함 (#160, #280)."""

import csv
import hashlib
import io
import json
import zipfile

import pytest

from app.schemas.admin_export import ExportFilters
from app.services.admin_export_service import AdminExportService

from .conftest import run


def _session_with_utterances(client, teacher, make_upload):
    upload_id = make_upload(teacher)
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
    return sid, target, upload_id


def _name(teacher, upload_id, sid, ext):
    # make_upload 첫 파일은 plan_0.pdf
    return (
        f"simulations/u{teacher.id:05d}__simsession_{upload_id}"
        f"__plan_0__s{sid}.{ext}"
    )


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
    sid, target, upload_id = _session_with_utterances(
        client, teacher, make_upload
    )
    zf = _zip(sim_db, ExportFilters())

    name = _name(teacher, upload_id, sid, "jsonl")
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
    assert "simulations/      수업 시뮬레이션 대화록·피드백 (.md)" in readme
    assert (
        "u{user_id}__simsession_{지도안번호}__{지도안이름}"
        "__s{세션번호}.{md|jsonl}" in readme
    )


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


@pytest.mark.parametrize("by_user", [False, True])
def test_zip_contains_session_markdown_with_manifest_digest(
    client, sim_db, teacher, make_upload, fake_gemini, by_user
):
    sid, target, upload_id = _session_with_utterances(
        client, teacher, make_upload
    )
    filters = ExportFilters(user_ids=[teacher.id] if by_user else None)
    zf = _zip(sim_db, filters)

    name = _name(teacher, upload_id, sid, "md")
    data = zf.read(name)
    md = data.decode()
    assert "teacher1" in md
    assert "- 지도안: plan_0.pdf" in md
    assert f"- **교사 ({target['display_name']}에게)**: 너는?" in md
    assert "피드백이 아직 생성되지 않았습니다." in md

    rows = {
        r["archive_path"]: r
        for r in csv.DictReader(io.StringIO(zf.read("manifest.csv").decode()))
    }
    assert rows[name]["kind"] == "simulation_report"
    assert rows[name]["session_id"] == str(sid)
    assert rows[name]["byte_size"] == str(len(data))
    assert rows[name]["sha256"] == hashlib.sha256(data).hexdigest()
    # 기존 jsonl 행은 그대로 남는다
    assert rows[name.replace(".md", ".jsonl")]["kind"] == "simulation"
