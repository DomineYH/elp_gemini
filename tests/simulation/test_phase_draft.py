"""지도안 국면 자동 분해 초안 (#155)."""

import pytest
from sqlalchemy import func, select

from app.models.simulation_phase import SimulationPhase
from app.services.simulation.llm_schemas import (
    PhaseDraftItem,
    PhaseSplitResult,
)

from .conftest import run

DRAFT = "/api/simulation/phases/draft"


def _split(n):
    return PhaseSplitResult(
        phases=[
            PhaseDraftItem(
                name=f"국면{i}",
                minutes=5,
                teacher_prompt=f"발문 {i}",
                task="",
                materials="",
                cautions="",
                source_span="",
            )
            for i in range(n)
        ]
    )


def _phase_count(sim_db):
    async def _go():
        async with sim_db() as db:
            return await db.scalar(select(func.count(SimulationPhase.id)))

    return run(_go())


def _create_session(client, phases):
    cands = client.get(
        "/api/simulation/candidates", params={"n": 2, "seed": 1}
    ).json()["candidates"]
    r = client.post(
        "/api/simulation/sessions",
        json={
            "personas": [
                {"ref": c["ref"], "pseudonym": c["pseudonym"]} for c in cands
            ],
            "phases": phases,
        },
    )
    assert r.status_code == 201
    return r.json()


@pytest.fixture
def ready(client, teacher, make_upload, fake_gemini):
    make_upload(teacher)
    return client


def _assert_fallback(body):
    assert body["source"] == "fallback"
    assert [p["name"] for p in body["phases"]] == ["도입", "활동1", "정리"]
    assert all(p["teacher_prompt"] == "" for p in body["phases"])
    assert body["notice"]


def test_generated_phases_from_plan(ready, fake_gemini, sim_db):
    r = ready.get(DRAFT)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "generated"
    assert body["notice"] is None
    assert [p["name"] for p in body["phases"]] == [
        "도입",
        "활동1",
        "활동2",
        "활동3",
        "정리",
    ]
    assert body["phases"][0]["teacher_prompt"] == "도입 발문"
    assert fake_gemini.count("phase_split") == 1
    assert _phase_count(sim_db) == 0


def test_parse_failure_falls_back(ready, fake_gemini):
    fake_gemini.parse_fail.add("phase_split")
    _assert_fallback(ready.get(DRAFT).json())


def test_two_phases_or_fewer_falls_back(ready, fake_gemini):
    fake_gemini.results["phase_split"] = _split(2)
    _assert_fallback(ready.get(DRAFT).json())


def test_more_than_eight_keeps_first_eight(ready, fake_gemini):
    fake_gemini.results["phase_split"] = _split(10)
    body = ready.get(DRAFT).json()
    assert body["source"] == "generated"
    assert [p["name"] for p in body["phases"]] == [f"국면{i}" for i in range(8)]


@pytest.mark.parametrize("key", ["quota", "overload"])
def test_quota_or_overload_falls_back_with_200(ready, fake_gemini, key):
    getattr(fake_gemini, key).add("phase_split")
    r = ready.get(DRAFT)
    assert r.status_code == 200
    _assert_fallback(r.json())


def test_empty_plan_text_falls_back_without_call(
    client, teacher, make_upload, fake_gemini
):
    make_upload(teacher, text="")
    _assert_fallback(client.get(DRAFT).json())
    assert fake_gemini.count("phase_split") == 0


def test_edited_phases_are_saved_and_inherited(ready, fake_gemini, sim_db):
    phases = ready.get(DRAFT).json()["phases"]
    assert _phase_count(sim_db) == 0
    phases[1]["name"] = "모둠 활동"
    phases[1]["teacher_prompt"] = "지도에서 우리 동네를 찾아볼까요?"
    phases[1]["materials"] = "지도 학습지"
    del phases[4]
    state = _create_session(ready, phases)
    assert [p["name"] for p in state["phases"]] == [
        "도입",
        "모둠 활동",
        "활동2",
        "활동3",
    ]
    splits = fake_gemini.count("phase_split")

    body = ready.get(DRAFT).json()
    assert body["source"] == "inherited"
    assert body["notice"] is None
    assert [p["name"] for p in body["phases"]] == [
        "도입",
        "모둠 활동",
        "활동2",
        "활동3",
    ]
    assert body["phases"][1]["teacher_prompt"] == (
        "지도에서 우리 동네를 찾아볼까요?"
    )
    assert body["phases"][1]["materials"] == "지도 학습지"
    assert fake_gemini.count("phase_split") == splits
    assert _phase_count(sim_db) == 4


def test_new_upload_is_not_inherited(ready, teacher, make_upload, fake_gemini):
    _create_session(ready, [{"name": "하나", "teacher_prompt": "발문"}])
    make_upload(teacher, text="Second lesson about rivers")
    assert ready.get(DRAFT).json()["source"] == "generated"


def test_no_upload_is_404(client, fake_gemini):
    r = client.get(DRAFT)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NO_UPLOAD"
    assert fake_gemini.count() == 0
