"""scripts/load_personas.py 정규화 규칙 단위 테스트 (#151)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "load_personas.py"

_spec = importlib.util.spec_from_file_location("load_personas", SCRIPT_PATH)
load_personas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(load_personas)


def _row(id_, grade="Grade 5 (Primary)", level="High: Top 10% of school"):
    return {
        "id": id_,
        "age": 11,
        "gender": "female",
        "grade": grade,
        "development_stage": {
            "piaget_cognitive_stage": "Concrete Operational Stage",
            "erikson_psychosocial_stage": "Industry vs. Inferiority",
            "kohlberg_moral_stage": "Conventional Level",
        },
        "strong_subjects": ["Art"],
        "weak_subjects": ["Mathematics"],
        "academic_level": level,
        "personality": f"Student {id_} is curious.",
        "values": "v",
        "social_relationships": "s",
        "creativity": "c",
        "mental_health": "m",
        "sampling_constraints": {"grade": grade},
    }


def test_mid_becomes_average_and_level_is_split():
    out = load_personas.normalize_rows(
        [_row(1, level="Mid: Ranked 10% to 30% in the school.")]
    )
    assert out[0]["academic_level"] == "Average"
    assert out[0]["academic_level_desc"] == "Ranked 10% to 30% in the school."


def test_grade_parsing_suffix_prefix_and_words():
    rows = [
        _row(1, grade="Grade 5 (Primary)"),
        _row(2, grade="Grade 6 (Primary)"),
        _row(3, grade="Fifth grade"),
        _row(4, grade="Sixth grade"),
        _row(5, grade="English: Grade 6 (or something)"),
    ]
    out = load_personas.normalize_rows(rows)
    assert [(r["id"], r["grade"]) for r in out] == [
        (1, 5),
        (2, 6),
        (3, 5),
        (4, 6),
        (5, 6),
    ]


def test_non_grade_5_6_rows_are_dropped():
    rows = [
        _row(1, grade="Grade 4 (Primary)"),
        _row(2, grade="English: Grade 7 (or First Year of Junior High School)"),
        _row(3, grade="Fourth grade"),
        _row(4, grade="六年级（因学业原因留级一年，现12岁）"),
        _row(5, grade="Grade 12 (Senior High)"),
        _row(6),
    ]
    assert [r["id"] for r in load_personas.normalize_rows(rows)] == [6]


def test_duplicate_id_keeps_first_and_output_sorted():
    first = _row(9, level="Low: Top 30%-50% of school")
    second = _row(9, level="Poor: Bottom 50% of school")
    out = load_personas.normalize_rows([_row(10), first, second, _row(2)])
    assert [r["id"] for r in out] == [2, 9, 10]
    assert out[1]["academic_level"] == "Low"


def test_fixed_key_order_without_sampling_constraints():
    out = load_personas.normalize_rows([_row(1)])
    assert list(out[0]) == [
        "id",
        "age",
        "gender",
        "grade",
        "academic_level",
        "academic_level_desc",
        "development_stage",
        "strong_subjects",
        "weak_subjects",
        "personality",
        "values",
        "social_relationships",
        "creativity",
        "mental_health",
    ]
