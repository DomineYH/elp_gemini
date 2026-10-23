"""
HACHIMI-1M Grade 5·6 페르소나 풀 (ADR 0002)
정규화된 jsonl을 읽어 후보를 seed로 재현 가능하게 추출한다.
"""

import json
import random
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.repositories.app_state_repository import (
    KEY_SIM_MAX_PERSONAS,
    AppStateRepository,
)
from app.services.simulation.errors import SimulationError

DATA_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "personas"
    / "hachimi_grade5_6_en.jsonl"
)
MIN_PERSONAS = 2
DEFAULT_MAX_PERSONAS = 4
LEVELS = ("High", "Average", "Low", "Poor")
_LEVEL_ALIASES = {"Mid": "Average"}
LEVEL_LABELS = {
    "High": "높은 도달",
    "Average": "안정적 도달",
    "Low": "부분 도달",
    "Poor": "추가 지원 필요",
}
# 표에 자주 나오는 교과만 매핑하고 나머지는 원문 그대로 둔다.
SUBJECT_KO = {
    "Mathematics": "수학",
    "English": "영어",
    "Chinese Language": "국어",
    "Chinese Language and Literature": "국어",
    "Art": "미술",
    "Fine Arts": "미술",
    "Science": "과학",
    "Geography": "사회(지리)",
    "History": "사회(역사)",
    "Information Technology": "정보",
    "Physical Education": "체육",
    "Physical Education or Sports": "체육",
    "Biology": "과학(생명)",
    "Music": "음악",
    "Physics": "과학(물리)",
    "Chemistry": "과학(화학)",
    "Politics": "사회",
    "Morality and Law": "도덕",
    "Moral Education": "도덕",
}
NAME_POOL = tuple(
    """
    서연 서윤 지우 서현 민서 하은 하윤 윤서 지유 지민
    채원 수아 지아 다은 예은 수빈 소율 예린 지원 유나
    민준 서준 도윤 예준 시우 하준 주원 지호 지후 준우
    준서 도현 건우 현우 우진 선우 연우 유준 정우 승우
    승현 시윤 준혁 은우 지환 민재 윤우 이준 태윤 하람
    다온 은서 가은 시은
    """.split()
)


def normalize_level(value: str) -> str:
    """'High' 또는 'High: 설명' → 범주. Mid→Average. 그 외는 ValueError."""
    cat = value.split(":", 1)[0].strip()
    cat = _LEVEL_ALIASES.get(cat, cat)
    if cat not in LEVELS:
        raise ValueError(f"unknown academic_level: {value!r}")
    return cat


@lru_cache(maxsize=1)
def load_pool() -> tuple[dict, ...]:
    with DATA_PATH.open(encoding="utf-8") as f:
        return tuple(json.loads(line) for line in f if line.strip())


def sample(pool, grade, level, n: int, seed: int) -> list[dict]:
    """grade: "all"|5|6, level: "all"|LEVELS.

    level "all"이면 섞은 4범주 순서를 돌아가며 한 명씩 뽑는다.
    """
    rng = random.Random(seed)
    rows = sorted(
        (r for r in pool if grade == "all" or r["grade"] == int(grade)),
        key=lambda r: r["id"],
    )
    buckets = {
        lv: [r for r in rows if r["academic_level"] == lv] for lv in LEVELS
    }
    order = rng.sample(LEVELS, 4) if level == "all" else [level]
    picked = []
    for i in range(n):
        bucket = buckets[order[i % len(order)]]
        record = rng.choice(bucket)
        bucket.remove(record)
        picked.append(record)
    return picked


def assign_pseudonyms(count: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    names = rng.sample(NAME_POOL, min(count, len(NAME_POOL)))
    # ponytail: count > len(NAME_POOL)이면 이름이 반복된다.
    # SIM_MAX_PERSONAS(6)가 풀보다 훨씬 작아 지금은 생기지 않는다.
    return [names[i % len(names)] for i in range(count)]


def _subject_ko(name: str) -> str:
    plain = name.removeprefix("English: ")
    return SUBJECT_KO.get(plain, plain)


SUMMARY_MAX_CHARS = 80


def summarize(text: str, limit: int = SUMMARY_MAX_CHARS) -> str:
    """limit자 안에서 단어 경계로 자르고, 잘랐으면 …을 붙인다 (#177)."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if text[limit] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:") + "…"


def to_candidate(record: dict, pseudonym: str) -> dict:
    return {
        "ref": str(record["id"]),
        "source": "dataset",
        "pseudonym": pseudonym,
        "grade": record["grade"],
        "level": record["academic_level"],
        "level_label": LEVEL_LABELS[record["academic_level"]],
        "strong_subjects": [_subject_ko(s) for s in record["strong_subjects"]],
        "weak_subjects": [_subject_ko(s) for s in record["weak_subjects"]],
        "behavior_summary": summarize(record["personality"]),
    }


@lru_cache(maxsize=1)
def _pool_by_id() -> dict[str, dict]:
    return {str(r["id"]): r for r in load_pool()}


def resolve_refs(refs: list[str]) -> list[dict]:
    """데이터셋 ref("123") → 원본 레코드. 모르는 ref → UNKNOWN_PERSONA.

    custom:<id>는 #158에서 session_service가 따로 푼다.
    """
    by_id = _pool_by_id()
    if any(ref not in by_id for ref in refs):
        raise SimulationError("UNKNOWN_PERSONA")
    return [by_id[ref] for ref in refs]


async def effective_max_personas(db) -> int:
    """관리자 설정값. 없거나 못 읽거나 범위 밖이면 기본값(절대 상한 이하)."""
    raw = await AppStateRepository(db).get(KEY_SIM_MAX_PERSONAS)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return min(DEFAULT_MAX_PERSONAS, settings.SIM_MAX_PERSONAS)
    if MIN_PERSONAS <= n <= settings.SIM_MAX_PERSONAS:
        return n
    return min(DEFAULT_MAX_PERSONAS, settings.SIM_MAX_PERSONAS)
