"""persona_pool 추출 규칙 단위 테스트 (#151)."""

import pytest

from app.services.simulation import persona_pool


def _pool():
    rows = []
    for i in range(1, 81):
        rows.append(
            {
                "id": i,
                "grade": 5 if i % 2 else 6,
                "academic_level": persona_pool.LEVELS[(i // 2) % 4],
                "strong_subjects": ["Mathematics"],
                "weak_subjects": ["English: Fine Arts", "Unmapped"],
                "personality": "x" * 100,
            }
        )
    return rows


def _refs(records):
    return [r["id"] for r in records]


def test_same_seed_gives_same_records_and_names():
    pool = _pool()
    a = persona_pool.sample(pool, "all", "all", 4, seed=42)
    b = persona_pool.sample(pool, "all", "all", 4, seed=42)
    assert _refs(a) == _refs(b)
    assert persona_pool.assign_pseudonyms(4, 42) == (
        persona_pool.assign_pseudonyms(4, 42)
    )


@pytest.mark.parametrize("seed", [1, 2, 3, 99])
def test_level_all_n4_takes_one_of_each_level(seed):
    picked = persona_pool.sample(_pool(), "all", "all", 4, seed=seed)
    assert sorted(r["academic_level"] for r in picked) == sorted(
        persona_pool.LEVELS
    )
    assert len(set(_refs(picked))) == 4


def test_n6_level_all_is_balanced_and_unique():
    picked = persona_pool.sample(_pool(), "all", "all", 6, seed=7)
    levels = [r["academic_level"] for r in picked]
    assert all(levels.count(lv) in (1, 2) for lv in persona_pool.LEVELS)
    assert len(set(_refs(picked))) == 6


def test_grade_and_fixed_level_filter():
    picked = persona_pool.sample(_pool(), 6, "Poor", 5, seed=3)
    assert {r["grade"] for r in picked} == {6}
    assert {r["academic_level"] for r in picked} == {"Poor"}
    assert len(set(_refs(picked))) == 5


def test_pseudonyms_unique_and_from_name_pool():
    names = persona_pool.assign_pseudonyms(6, 123)
    assert len(set(names)) == 6
    assert set(names) <= set(persona_pool.NAME_POOL)
    assert len(set(persona_pool.NAME_POOL)) >= 50


def test_to_candidate_maps_labels_and_truncates_summary():
    cand = persona_pool.to_candidate(_pool()[0], "서연")
    assert cand == {
        "ref": "1",
        "source": "dataset",
        "pseudonym": "서연",
        "grade": 5,
        "level": "High",
        "level_label": "높은 도달",
        "strong_subjects": ["수학"],
        "weak_subjects": ["미술", "Unmapped"],
        "behavior_summary": "x" * 80 + "…",
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("short sentence.", "short sentence."),
        ("a" * 80, "a" * 80),
        (
            "Student No. 9313 demonstrates strong self-discipline and a "
            "sense of responsibility in class.",
            "Student No. 9313 demonstrates strong self-discipline and a "
            "sense of…",
        ),
        ("word " * 16 + "end", "word " * 15 + "word…"),
        ("  extra   spaces  ", "extra spaces"),
    ],
)
def test_summarize_cuts_on_word_boundary_with_ellipsis(text, expected):
    """단어 중간에서 잘리지 않고, 잘렸으면 …로 끝난다 (#177)."""
    out = persona_pool.summarize(text)
    assert out == expected
    assert len(out) <= persona_pool.SUMMARY_MAX_CHARS + 1


def test_committed_pool_summaries_never_cut_mid_word():
    for record in persona_pool.load_pool()[:200]:
        out = persona_pool.to_candidate(record, "서연")["behavior_summary"]
        if out.endswith("…"):
            head = out[:-1]
            full = " ".join(record["personality"].split())
            assert full.startswith(head)
            assert full[len(head)] in " ,.;:"


def test_committed_pool_loads_grade_5_and_6_only():
    pool = persona_pool.load_pool()
    assert len(pool) > 1500
    assert {r["grade"] for r in pool} == {5, 6}
    assert {r["academic_level"] for r in pool} == set(persona_pool.LEVELS)
