"""설정 화면과 후보 API (#151)."""

import pytest


def test_candidates_shape_and_seed_reproducible(client):
    r = client.get(
        "/api/simulation/candidates",
        params={"grade": "all", "level": "all", "n": 4, "seed": 7},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["seed"] == 7
    cands = body["candidates"]
    assert len(cands) == 4
    assert set(cands[0]) == {
        "ref",
        "source",
        "pseudonym",
        "grade",
        "level",
        "level_label",
        "strong_subjects",
        "weak_subjects",
        "behavior_summary",
    }
    assert sorted(c["level"] for c in cands) == [
        "Average",
        "High",
        "Low",
        "Poor",
    ]
    again = client.get(
        "/api/simulation/candidates",
        params={"grade": "all", "level": "all", "n": 4, "seed": 7},
    ).json()
    assert again == body


def test_candidates_without_seed_returns_server_seed(client):
    body = client.get("/api/simulation/candidates").json()
    assert isinstance(body["seed"], int)
    assert len(body["candidates"]) == 4


def test_candidates_grade_and_level_filter(client):
    cands = client.get(
        "/api/simulation/candidates",
        params={"grade": "5", "level": "Poor", "n": 3, "seed": 1},
    ).json()["candidates"]
    assert {(c["grade"], c["level"]) for c in cands} == {(5, "Poor")}
    assert {c["level_label"] for c in cands} == {"추가 지원 필요"}


@pytest.mark.parametrize("n", [1, 7])
def test_candidates_count_out_of_range_is_422(client, n):
    r = client.get("/api/simulation/candidates", params={"n": n})
    assert r.status_code == 422


def test_setup_without_upload_points_to_dashboard(client):
    r = client.get("/simulation/setup")
    assert r.status_code == 200
    assert 'href="/dashboard"' in r.text
    assert 'id="candRows"' not in r.text


def test_setup_with_upload_shows_candidate_table(client, teacher, make_upload):
    make_upload(teacher, text="Intro lesson about maps")
    r = client.get("/simulation/setup")
    assert r.status_code == 200
    assert 'id="candRows"' in r.text
    assert "Intro lesson about maps" in r.text
    assert "HACHIMI-1M" in r.text


def test_setup_uses_own_upload_only(
    client, teacher, other_teacher, make_upload, as_user
):
    make_upload(teacher)
    as_user(other_teacher)
    r = client.get("/simulation/setup")
    assert 'id="candRows"' not in r.text
