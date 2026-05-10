#!/usr/bin/env python3
"""
이모지 재유입 차단 정적 점검 스크립트

분석 보고서·프롬프트의 `## lesson_analysis` 섹션·OpenAPI 스키마 예시에
이모지·픽토그램·키캡 결합 문자가 다시 들어오는 것을 CI 단계에서 차단한다.

기본 스캔 대상 (인자 없이 실행 시):
1. `prompt/prompt.md` — `## lesson_analysis` 섹션 본문만 (가드 블록 제외).
2. `app/schemas/lessonplan_analysis.py` — 파일 전체.
3. `app/static/reports/*_reports.md` — 인용(`>`) 줄 제외.

명시적 파일 인자가 주어지면 해당 파일들만 검사하며, 파일 경로 휴리스틱
으로 어떤 예외 규칙을 적용할지 결정한다 (`prompt.md` / `prompt/` 하위 →
프롬프트 규칙, `*_reports.md` → 인용 줄 예외, 그 외 → 전체 검사).
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path
from typing import List, Tuple

# 프로젝트 루트 — sys.path 부트스트랩(`from app...` CLI 직접 실행 호환) 과
# 기본 스캔 대상 경로 해석에 모두 사용한다.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.text_sanitizer import _EMOJI_PATTERN  # noqa: E402

DEFAULT_PROMPT_PATH: Path = PROJECT_ROOT / "prompt" / "prompt.md"
DEFAULT_SCHEMA_PATH: Path = (
    PROJECT_ROOT / "app" / "schemas" / "lessonplan_analysis.py"
)
DEFAULT_REPORTS_GLOB: str = str(
    PROJECT_ROOT / "app" / "static" / "reports" / "*_reports.md"
)

LESSON_ANALYSIS_HEADER: str = "## lesson_analysis"
GUARD_BLOCK_LABEL_PREFIX: str = "**출력 형식 엄격 규칙:"

# 한 발견: (라인 번호 1-based, 컬럼 1-based, 매칭된 이모지 문자열)
Finding = Tuple[int, int, str]


def _is_prompt_file(path: Path) -> bool:
    """파일명이 `prompt.md` 이거나 `prompt/` 디렉터리 하위인지 판정."""
    if path.name == "prompt.md":
        return True
    return any(parent.name == "prompt" for parent in path.parents)


def _is_report_file(path: Path) -> bool:
    """파일명이 `*_reports.md` 패턴과 일치하는지 판정."""
    return path.name.endswith("_reports.md")


def _find_emojis_in_line(line: str) -> List[Tuple[int, str]]:
    """한 줄 안의 모든 이모지 매치를 (1-based 컬럼, 문자열) 튜플 리스트로 반환."""
    return [(m.start() + 1, m.group(0)) for m in _EMOJI_PATTERN.finditer(line)]


def _scan_prompt(lines: List[str]) -> List[Finding]:
    """
    프롬프트 파일에서 `## lesson_analysis` 섹션만 검사한다.

    상태 머신:
    - `in_section`: `## lesson_analysis` 헤더 이후, 다음 stand-alone `---`
      구분선 이전 구간에서 True. 단, 코드 펜스(```) 내부의 `---` 는
      섹션 종료로 간주하지 않는다.
    - `in_guard_block`: `**출력 형식 엄격 규칙:` 라벨 이후, 첫 빈 줄 또는
      다음 `**굵은 라벨**` 줄, 또는 비-bullet 줄을 만날 때까지 True.
      가드 블록 내부의 줄(라벨 자체와 그 직후 bullet들)은 부정 예시이므로
      이모지 검사를 건너뛴다.
    """
    findings: List[Finding] = []
    in_section = False
    in_code_fence = False
    in_guard_block = False

    for line_no, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        lstripped = raw.lstrip()

        if not in_section:
            if stripped == LESSON_ANALYSIS_HEADER:
                in_section = True
            continue

        # 코드 펜스 토글 — 펜스 내부의 `---` 는 섹션 종료가 아님
        if lstripped.startswith("```"):
            in_code_fence = not in_code_fence
            # 펜스 마커 자체는 검사 대상에서 제외
            continue

        # 섹션 종료: 코드 펜스 밖에서 만난 stand-alone `---`
        if not in_code_fence and stripped == "---":
            break

        # 가드 블록 상태 전이
        if in_guard_block:
            if stripped == "":
                in_guard_block = False
                continue
            if lstripped.startswith("**"):
                # 다음 굵은 라벨 줄 — 가드 블록 종료, 이 줄은 정상 검사 대상
                in_guard_block = False
                # fall through to scan
            elif not lstripped.startswith("-"):
                # bullet 이 아닌 줄 — 가드 블록 종료, 정상 검사 대상
                in_guard_block = False
                # fall through to scan
            else:
                # 가드 블록 내부 bullet — 부정 예시 이모지 허용
                continue

        if not in_guard_block and lstripped.startswith(
            GUARD_BLOCK_LABEL_PREFIX
        ):
            in_guard_block = True
            # 라벨 줄 자체도 부정 예시를 포함할 수 있으므로 건너뜀
            continue

        for col, emoji in _find_emojis_in_line(raw):
            findings.append((line_no, col, emoji))

    return findings


def _scan_report(lines: List[str]) -> List[Finding]:
    """보고서 파일에서 인용(`>`) 줄을 제외한 본문만 검사."""
    findings: List[Finding] = []
    for line_no, raw in enumerate(lines, start=1):
        if raw.lstrip().startswith(">"):
            continue
        for col, emoji in _find_emojis_in_line(raw):
            findings.append((line_no, col, emoji))
    return findings


def _scan_full(lines: List[str]) -> List[Finding]:
    """예외 없이 전체 파일을 검사."""
    findings: List[Finding] = []
    for line_no, raw in enumerate(lines, start=1):
        for col, emoji in _find_emojis_in_line(raw):
            findings.append((line_no, col, emoji))
    return findings


def _scan_file(path: Path) -> List[Finding]:
    """파일 경로 휴리스틱으로 적절한 검사 함수를 골라 실행."""
    text = path.read_text(encoding="utf-8")
    # splitlines() 는 후행 개행을 보존하지 않지만, 컬럼 계산에는 영향 없음
    lines = text.splitlines()
    if _is_prompt_file(path):
        return _scan_prompt(lines)
    if _is_report_file(path):
        return _scan_report(lines)
    return _scan_full(lines)


def _resolve_targets(explicit: List[str]) -> List[Path]:
    """명시 인자 우선, 없으면 기본 스캔 대상 목록을 반환."""
    if explicit:
        return [Path(arg) for arg in explicit]

    targets: List[Path] = []
    if DEFAULT_PROMPT_PATH.exists():
        targets.append(DEFAULT_PROMPT_PATH)
    if DEFAULT_SCHEMA_PATH.exists():
        targets.append(DEFAULT_SCHEMA_PATH)
    targets.extend(sorted(Path(p) for p in glob.glob(DEFAULT_REPORTS_GLOB)))
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "분석 보고서·프롬프트·OpenAPI 예시의 이모지 재유입을 차단하는"
            " 정적 점검."
        )
    )
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "검사할 파일 경로. 지정 시 기본 스캔 대상 무시. 미지정 시 "
            "prompt/prompt.md, app/schemas/lessonplan_analysis.py, "
            "app/static/reports/*_reports.md 를 검사."
        ),
    )
    args = parser.parse_args(argv)

    targets = _resolve_targets(args.files)

    total_findings = 0
    for path in targets:
        for line_no, col, emoji in _scan_file(path):
            print(f"{path}:{line_no}:{col}:{emoji}", file=sys.stderr)
            total_findings += 1

    if total_findings:
        return 1
    print(f"OK: scanned {len(targets)} files, no emoji regressions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
