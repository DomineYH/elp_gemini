"""
HACHIMI-1M 영어 샘플에서 Grade 5·6 페르소나만 정규화해 저장한다 (ADR 0002).

사용법:
    python scripts/load_personas.py <merged_students_10k_EN.jsonl>
        [--out data/personas/hachimi_grade5_6_en.jsonl]
"""

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.simulation.persona_pool import normalize_level  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "data" / "personas" / "hachimi_grade5_6_en.jsonl"
KEEP_GRADES = (5, 6)
_GRADE_NUM = re.compile(r"^(?:English: )?Grade (\d+)")
_GRADE_WORD = re.compile(r"^(fifth|sixth) grade", re.IGNORECASE)
_WORD_TO_NUM = {"fifth": 5, "sixth": 6}
KEY_ORDER = (
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
)


def parse_grade(value: str) -> int | None:
    m = _GRADE_NUM.match(value)
    if m:
        return int(m.group(1))
    m = _GRADE_WORD.match(value)
    return _WORD_TO_NUM[m.group(1).lower()] if m else None


def normalize_rows(rows) -> list[dict]:
    """Grade 5·6만 남기고 정규화. 중복 id는 파일 순서상 첫 행만 유지."""
    by_id: dict[int, dict] = {}
    for row in rows:
        grade = parse_grade(row["grade"])
        if grade not in KEEP_GRADES or row["id"] in by_id:
            continue
        _, _, desc = row["academic_level"].partition(":")
        values = {
            **row,
            "grade": grade,
            "academic_level": normalize_level(row["academic_level"]),
            "academic_level_desc": desc.strip(),
        }
        by_id[row["id"]] = {k: values[k] for k in KEY_ORDER}
    return [by_id[k] for k in sorted(by_id)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    with args.src.open(encoding="utf-8") as f:
        rows = normalize_rows(json.loads(line) for line in f if line.strip())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    counts: dict[tuple[int, str], int] = {}
    for row in rows:
        key = (row["grade"], row["academic_level"])
        counts[key] = counts.get(key, 0) + 1
    print(f"wrote {len(rows)} rows -> {args.out}")
    for key in sorted(counts):
        print(f"  grade {key[0]} {key[1]}: {counts[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
