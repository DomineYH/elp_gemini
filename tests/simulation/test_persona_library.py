"""내 학생 페르소나 라이브러리 (#158)."""

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import ensure_simulation_tables
from app.models.simulation_persona_library import SimulationPersonaLibraryItem

from .conftest import run

PROFILE = {
    "age": 11,
    "gender": "female",
    "grade": 5,
    "academic_level": "Poor",
    "development_stage": {
        "piaget_cognitive_stage": "Concrete Operational Stage",
        "erikson_psychosocial_stage": "Industry vs. Inferiority",
        "kohlberg_moral_stage": "Conventional Level",
    },
    "strong_subjects": ["Art"],
    "weak_subjects": ["Mathematics"],
    "personality": "발표를 좋아하지만 먼저 끝내면 옆 친구에게 말을 건다.",
    "values": "모둠 규칙을 지키려 한다.",
    "social_relationships": "친한 친구 두 명과만 모둠을 하려 한다.",
    "creativity": "그림으로 생각을 정리한다.",
    "mental_health": "틀리면 고개를 숙이고 말수가 줄어든다.",
}


@pytest.fixture
def lib(client, fake_gemini):
    return client


def _error_code(r):
    return r.json()["detail"]["code"]


def test_invalid_json_is_400(lib):
    r = lib.post(
        "/api/simulation/library",
        content="{not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert _error_code(r) == "INVALID_PERSONA"


@pytest.mark.parametrize(
    "change",
    [
        {"nickname": "x"},
        {"academic_level": "Medium"},
        {"grade": 7},
        {"gender": "unknown"},
    ],
)
def test_schema_violations_are_400(lib, fake_gemini, change):
    r = lib.post("/api/simulation/library", json={**PROFILE, **change})
    assert r.status_code == 400
    assert _error_code(r) == "INVALID_PERSONA"
    assert fake_gemini.count("adapt") == 0


def test_missing_key_is_400(lib):
    body = {k: v for k, v in PROFILE.items() if k != "values"}
    r = lib.post("/api/simulation/library", json=body)
    assert r.status_code == 400


def _create(client, **change):
    r = client.post("/api/simulation/library", json={**PROFILE, **change})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_adapts_once_and_stores_item(lib, fake_gemini):
    item = _create(lib, academic_level="High: Top 10%")
    assert fake_gemini.calls == [("adapt", None)]
    assert item["ref"] == f"custom:{item['id']}"
    assert item["adapted_level"] == "높은 도달"
    assert item["raw_profile"]["academic_level"] == "High"
    assert item["adapted_profile"]["behavior_summary"]


def test_adapt_parse_failure_saves_nothing(lib, fake_gemini):
    fake_gemini.parse_fail.add("adapt")
    r = lib.post("/api/simulation/library", json=PROFILE)
    assert r.status_code == 502
    assert _error_code(r) == "ADAPT_FAILED"
    assert lib.get("/api/simulation/library").json()["items"] == []


def _ids(client):
    items = client.get("/api/simulation/library").json()["items"]
    return [i["id"] for i in items]


def _custom_candidates(client):
    cands = client.get(
        "/api/simulation/candidates", params={"n": 4, "seed": 3}
    ).json()["candidates"]
    assert [c["source"] for c in cands[:4]] == ["dataset"] * 4
    return cands[4:]


def test_list_and_candidates_show_own_items_only(
    lib, as_user, teacher, other_teacher
):
    mine = _create(lib)
    as_user(other_teacher)
    theirs = _create(lib, grade=6)
    assert _ids(lib) == [theirs["id"]]
    as_user(teacher)
    assert _ids(lib) == [mine["id"]]

    [cand] = _custom_candidates(lib)
    assert cand["ref"] == f"custom:{mine['id']}"
    assert cand["source"] == "custom"
    assert cand["grade"] == 5
    assert cand["level_label"] == "추가 지원 필요"
    dataset_names = {
        c["pseudonym"]
        for c in lib.get(
            "/api/simulation/candidates", params={"n": 4, "seed": 3}
        ).json()["candidates"][:4]
    }
    assert cand["pseudonym"] not in dataset_names


def test_delete_own_item_and_foreign_is_404(
    lib, as_user, teacher, other_teacher
):
    mine = _create(lib)
    as_user(other_teacher)
    r = lib.delete(f"/api/simulation/library/{mine['id']}")
    assert r.status_code == 404
    assert _error_code(r) == "LIBRARY_NOT_FOUND"
    as_user(teacher)
    assert (
        lib.delete(f"/api/simulation/library/{mine['id']}").status_code == 204
    )
    assert _ids(lib) == []
    assert _custom_candidates(lib) == []


PHASES = [{"name": "도입", "minutes": 5, "teacher_prompt": "지도를 보세요."}]


def _session_body(client, custom_ref):
    [dataset] = client.get(
        "/api/simulation/candidates", params={"n": 2, "seed": 5}
    ).json()["candidates"][:1]
    return {
        "personas": [
            {"ref": dataset["ref"], "pseudonym": "서연"},
            {"ref": custom_ref, "pseudonym": "민준"},
        ],
        "phases": PHASES,
    }


def test_mixed_session_snapshots_custom_persona(
    lib, teacher, make_upload, fake_gemini
):
    make_upload(teacher)
    item = _create(lib)
    adapt_before = fake_gemini.count("adapt")

    r = lib.post(
        "/api/simulation/sessions", json=_session_body(lib, item["ref"])
    )
    assert r.status_code == 201, r.text
    assert fake_gemini.count("adapt") - adapt_before == 1
    sid = r.json()["session"]["id"]
    dataset, custom = r.json()["personas"]
    assert dataset["source"] == "dataset"
    assert custom["source"] == "custom"
    assert custom["source_record_id"] == item["id"]
    assert custom["display_name"] == "민준"
    assert custom["adapted_level"] == "추가 지원 필요"
    assert custom["adapted_profile"] == item["adapted_profile"]

    # 첫 국면 학생 호출의 persona_key도 custom ref
    lib.post(f"/api/simulation/sessions/{sid}/phases/0/enter")
    assert ("student", item["ref"]) in fake_gemini.calls

    assert (
        lib.delete(f"/api/simulation/library/{item['id']}").status_code == 204
    )
    after = lib.get(f"/api/simulation/sessions/{sid}").json()["personas"][1]
    assert after == custom


@pytest.mark.parametrize("ref", ["custom:999", "custom:abc", "custom:01"])
def test_unknown_custom_ref_is_422(lib, teacher, make_upload, ref):
    make_upload(teacher)
    assert _create(lib)["id"] == 1  # custom:01이 이 항목으로 풀리면 안 된다
    r = lib.post("/api/simulation/sessions", json=_session_body(lib, ref))
    assert r.status_code == 422
    assert _error_code(r) == "UNKNOWN_PERSONA"


def test_other_users_custom_ref_is_422(
    lib, as_user, teacher, other_teacher, make_upload
):
    make_upload(teacher)
    as_user(other_teacher)
    theirs = _create(lib)
    as_user(teacher)
    r = lib.post(
        "/api/simulation/sessions", json=_session_body(lib, theirs["ref"])
    )
    assert r.status_code == 422
    assert _error_code(r) == "UNKNOWN_PERSONA"


def test_library_model_matches_ddl(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")

    async def _cols():
        await ensure_simulation_tables(engine)
        async with engine.connect() as conn:
            cols = await conn.run_sync(
                lambda c: inspect(c).get_columns("simulation_persona_library")
            )
        await engine.dispose()
        return {col["name"] for col in cols}

    table = SimulationPersonaLibraryItem.__table__
    assert run(_cols()) == {c.name for c in table.columns}


def test_setup_page_offers_custom_persona_modal(lib, teacher, make_upload):
    make_upload(teacher)
    html = lib.get("/simulation/setup").text
    assert 'id="modeCustom"' in html
    assert 'id="customModal"' in html
    assert "Poor → 추가 지원 필요" in html
    assert "임상 용어 없이 수업 중 행동으로" in html
