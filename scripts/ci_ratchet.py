#!/usr/bin/env python3
"""
CI 래칫 검사: 기존 실패는 허용하고 새 실패만 막는다.

서브커맨드
- tests: pytest 실패 집합을 tests/known_failures.txt 와 비교한다.
  새 실패(new)나 목록에 있는데 통과한 항목(fixed)이 있으면 exit 1.
  `--update` 는 현재 실패 집합으로 목록을 다시 쓴다.
- lint --base REV [files...]: 바뀐 .py 파일마다 base 와 head 를 비교해
  ruff 위반 수가 늘었거나 black 이 새로 깨졌으면 exit 1.

표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_KNOWN = "tests/known_failures.txt"
PYTEST_CMD = [
    sys.executable,
    "-m",
    "pytest",
    "-q",
    "-p",
    "no:cacheprovider",
    "--continue-on-collection-errors",
    "-rfE",
]
# 로그 줄(`ERROR    app.services...`)은 공백이 여럿이라 걸리지 않는다.
SUMMARY_RE = re.compile(r"^(FAILED|ERROR) (tests/.*)$")


def parse_failures(lines) -> set[str]:
    """pytest 요약 줄에서 `FAILED <id>` / `ERROR <id>` 집합을 뽑는다."""
    found = set()
    for line in lines:
        m = SUMMARY_RE.match(line.rstrip("\n"))
        if m:
            # ponytail: 노드 ID 자체에 " - " 가 들어간 parametrize 는 잘린다
            node_id = m.group(2).split(" - ", 1)[0].strip()
            found.add(f"{m.group(1)} {node_id}")
    return found


def read_known(text: str) -> set[str]:
    return {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def render_known(old_text: str, actual: set[str]) -> str:
    """맨 위 `#` 주석 헤더를 보존하고 실제 집합을 정렬해서 붙인다."""
    header = []
    for line in old_text.splitlines():
        if not line.startswith("#"):
            break
        header.append(line)
    return "\n".join(header + sorted(actual)) + "\n"


def compare(actual: set[str], known: set[str]) -> tuple[set[str], set[str]]:
    """(new, fixed) 를 돌려준다."""
    return actual - known, known - actual


def cmd_tests(args) -> int:
    proc = subprocess.Popen(
        PYTEST_CMD,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = []
    for line in proc.stdout:
        sys.stdout.write(line)
        lines.append(line)
    code = proc.wait()
    sys.stdout.flush()
    if code not in (0, 1):
        print(f"\n[ratchet] pytest 비정상 종료 (exit {code})")
        return 1

    actual = parse_failures(lines)
    known_path = Path(args.known)
    old_text = known_path.read_text(encoding="utf-8")
    if args.update:
        known_path.write_text(render_known(old_text, actual), encoding="utf-8")
        print(f"\n[ratchet] {known_path} 갱신: {len(actual)}건")
        return 0

    new, fixed = compare(actual, read_known(old_text))
    print(
        f"\n[ratchet] 실패 {len(actual)}건, "
        f"new {len(new)}, fixed {len(fixed)}"
    )
    for item in sorted(new):
        print(f"  new: {item}")
    for item in sorted(fixed):
        print(f"  fixed: {item}")
    if fixed:
        print(
            f"[ratchet] fixed 항목을 {known_path} 에서 지워라 "
            "(목록은 줄어들기만 한다)."
        )
    return 1 if new or fixed else 0


def git_show(rev: str, path: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"{rev}:{path}"], capture_output=True, text=True
    )
    return proc.stdout if proc.returncode == 0 else None


def ruff_violations(path: str, source: str) -> list[dict]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--output-format",
            "json",
            "--stdin-filename",
            path,
            "-",
        ],
        input=source,
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"ruff 실패 ({path}): {proc.stderr}")
    return json.loads(proc.stdout or "[]")


def black_ok(path: str, source: str) -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "black",
            "--line-length",
            "80",
            "--check",
            "-q",
            "--stdin-filename",
            path,
            "-",
        ],
        input=source,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def lint_verdict(
    ruff_base: int, ruff_head: int, black_base: bool, black_head: bool
) -> list[str]:
    """위반 사유 목록(비면 통과). 새 파일은 ruff_base=0, black_base=True."""
    reasons = []
    if ruff_head > ruff_base:
        reasons.append(f"ruff 위반 {ruff_base} -> {ruff_head}")
    if black_base and not black_head:
        reasons.append("black 포맷이 새로 깨짐")
    return reasons


def changed_files(base: str) -> list[str]:
    out = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            f"{base}...HEAD",
            "--",
            "*.py",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def cmd_lint(args) -> int:
    # ponytail: 이름만 바뀐 파일은 base 가 없어 새 파일로 취급된다
    files = args.files or changed_files(args.base)
    failed = 0
    for path in files:
        head = Path(path).read_text(encoding="utf-8")
        base = git_show(args.base, path)
        head_ruff = ruff_violations(path, head)
        reasons = lint_verdict(
            len(ruff_violations(path, base)) if base is not None else 0,
            len(head_ruff),
            black_ok(path, base) if base is not None else True,
            black_ok(path, head),
        )
        if reasons:
            failed += 1
            print(f"{path}: {', '.join(reasons)}")
            for v in head_ruff:
                loc = v["location"]
                print(
                    f"  {path}:{loc['row']}:{loc['column']}: "
                    f"{v['code']} {v['message']}"
                )
    print(f"[ratchet] lint: {len(files)}개 파일 검사, {failed}개 실패")
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = parser.add_subparsers(dest="command", required=True)
    tests = sub.add_parser("tests")
    tests.add_argument("--known", default=DEFAULT_KNOWN)
    tests.add_argument("--update", action="store_true")
    lint = sub.add_parser("lint")
    lint.add_argument("--base", required=True)
    lint.add_argument("files", nargs="*")
    args = parser.parse_args(argv)
    return cmd_tests(args) if args.command == "tests" else cmd_lint(args)


if __name__ == "__main__":
    sys.exit(main())
