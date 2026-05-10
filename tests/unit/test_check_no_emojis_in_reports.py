"""
check_no_emojis_in_reports CLI 단위 테스트

이모지 재유입 차단 정적 점검 스크립트의 검출 규칙·예외 처리·종료 코드 검증.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_no_emojis_in_reports.py"


def _load_main() -> Callable[[list[str] | None], int]:
    """스크립트의 main(argv) 함수를 동적으로 임포트한다."""
    spec = importlib.util.spec_from_file_location(
        "check_no_emojis_in_reports", str(SCRIPT_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


main = _load_main()


# 가드 블록 안에서만 등장이 허용되는 부정 예시 이모지
_FORBIDDEN_LIST_LINE = (
    "- 보고서 본문에 이모지·픽토그램·아이콘 문자(예: 📑, 1️⃣, 📊, 💡)"
    "를 절대 포함하지 마세요."
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestCleanFiles:
    def test_clean_files_exit_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """이모지가 없는 파일들은 종료 코드 0과 stdout 요약을 반환한다."""
        prompt = _write(
            tmp_path,
            "prompt.md",
            "## lesson_analysis\n\n본문 내용\n\n---\n",
        )
        report = _write(
            tmp_path,
            "sample_reports.md",
            "# 보고서\n\n## 1. 항목\n\n본문\n",
        )
        schema = _write(tmp_path, "schema.py", "x = 1\n")

        rc = main([str(prompt), str(report), str(schema)])

        captured = capsys.readouterr()
        assert rc == 0
        assert captured.err == ""
        assert "OK: scanned 3 files" in captured.out


class TestPromptHeuristic:
    def test_emoji_in_prompt_lesson_analysis_section_detected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """lesson_analysis 섹션 본문 이모지는 file:line:col:emoji 형식으로 보고된다."""
        content = (
            "# 헤더\n"
            "\n"
            "## lesson_analysis\n"
            "\n"
            "보고서 📊 본문\n"
            "\n"
            "---\n"
        )
        prompt = _write(tmp_path, "prompt.md", content)

        rc = main([str(prompt)])

        captured = capsys.readouterr()
        assert rc == 1
        # 5번째 줄의 4번째 컬럼(`보고서 ` 다음)에 📊
        assert f"{prompt}:5:5:📊" in captured.err
        # 성공 요약은 출력되지 않아야 함
        assert "OK: scanned" not in captured.out

    def test_emoji_in_prompt_guard_block_allowed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """**출력 형식 엄격 규칙:** 가드 블록 안의 부정 예시 이모지는 허용된다."""
        content = (
            "## lesson_analysis\n"
            "\n"
            "본문 텍스트\n"
            "\n"
            "**출력 형식 엄격 규칙:**\n"
            f"{_FORBIDDEN_LIST_LINE}\n"
            "- 헤더와 본문은 한글, 영문, 숫자만 사용합니다.\n"
            "- 키캡 숫자(1️⃣, 2️⃣ 등)는 일반 숫자로 대체합니다.\n"
            "\n"
            "**작성 태도**:\n"
            "- 건설적 피드백 제공\n"
            "\n"
            "---\n"
        )
        prompt = _write(tmp_path, "prompt.md", content)

        rc = main([str(prompt)])

        captured = capsys.readouterr()
        assert rc == 0
        assert captured.err == ""

    def test_emoji_in_prompt_outside_lesson_analysis_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """## lesson_analysis 섹션 밖(예: ## evaluation)의 이모지는 무시된다."""
        content = (
            "## evaluation\n"
            "\n"
            "평가 ✅ 좋은 답변 ❌ 나쁜 답변\n"
            "\n"
            "---\n"
            "\n"
            "## lesson_analysis\n"
            "\n"
            "깨끗한 본문\n"
            "\n"
            "---\n"
        )
        prompt = _write(tmp_path, "prompt.md", content)

        rc = main([str(prompt)])

        captured = capsys.readouterr()
        assert rc == 0
        assert captured.err == ""

    def test_emoji_after_lesson_analysis_section_close_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """lesson_analysis 섹션 종료(---) 이후의 이모지는 무시된다."""
        content = (
            "## lesson_analysis\n"
            "\n"
            "깨끗한 본문\n"
            "\n"
            "---\n"
            "\n"
            "## qna\n"
            "\n"
            "이후 섹션 📝 무관\n"
        )
        prompt = _write(tmp_path, "prompt.md", content)

        rc = main([str(prompt)])

        assert rc == 0
        assert capsys.readouterr().err == ""


class TestSchemaHeuristic:
    def test_emoji_in_schema_file_detected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """일반 .py 파일의 이모지는 (예외 없이) 모두 검출된다."""
        content = (
            '"""docstring"""\n'
            "x = '📑 보고서 헤더'\n"
            "y = 2\n"
        )
        schema = _write(tmp_path, "lessonplan_analysis.py", content)

        rc = main([str(schema)])

        captured = capsys.readouterr()
        assert rc == 1
        assert f"{schema}:2:6:📑" in captured.err


class TestReportHeuristic:
    def test_emoji_in_report_body_detected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """*_reports.md 본문(인용이 아닌 줄)의 이모지는 검출된다."""
        content = (
            "# 보고서\n"
            "\n"
            "본문 ✅ 강점\n"
        )
        report = _write(tmp_path, "1_x_reports.md", content)

        rc = main([str(report)])

        captured = capsys.readouterr()
        assert rc == 1
        assert f"{report}:3:4:✅" in captured.err

    def test_emoji_in_report_quote_line_allowed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """*_reports.md 의 인용(`>`) 줄에 있는 이모지는 허용된다."""
        content = (
            "# 보고서\n"
            "\n"
            "> 사용자 지도안 인용 📑 원본 보존\n"
            "    > 들여쓰기 인용 ✨ 보존\n"
            "\n"
            "본문 깨끗\n"
        )
        report = _write(tmp_path, "1_x_reports.md", content)

        rc = main([str(report)])

        captured = capsys.readouterr()
        assert rc == 0
        assert captured.err == ""

    def test_keycap_digit_in_report_body_detected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """키캡 결합 문자(1️⃣)도 본문에 등장하면 검출된다."""
        content = (
            "# 보고서\n"
            "\n"
            "1️⃣ 첫 번째 항목\n"
        )
        report = _write(tmp_path, "1_x_reports.md", content)

        rc = main([str(report)])

        captured = capsys.readouterr()
        assert rc == 1
        # 키캡 결합 문자 시퀀스가 검출되어 보고됨 (정확한 컬럼은 인코딩에 의존하지 않게 줄 단위로만 확인)
        assert f"{report}:3:" in captured.err


class TestAccumulationAndArgs:
    def test_multiple_findings_all_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """여러 발견이 누적되어 모두 stderr 로 보고되어야 한다."""
        report1 = _write(
            tmp_path, "1_a_reports.md", "본문 📊 첫 번째\n"
        )
        report2 = _write(
            tmp_path,
            "2_b_reports.md",
            "본문 ✅ 두 번째\n다른 줄 💡 세 번째\n",
        )

        rc = main([str(report1), str(report2)])

        captured = capsys.readouterr()
        assert rc == 1
        err_lines = [
            line for line in captured.err.splitlines() if line.strip()
        ]
        # 첫 파일 1건 + 두 번째 파일 2건 = 총 3건이 모두 보고되어야 함
        assert len(err_lines) == 3
        assert any("📊" in line for line in err_lines)
        assert any("✅" in line for line in err_lines)
        assert any("💡" in line for line in err_lines)

    def test_explicit_file_args_override_defaults(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """명시적 파일 인자가 주어지면 기본 스캔 대상은 무시되고 인자만 검사된다."""
        # 일부러 lesson_analysis 섹션 안에 이모지를 넣은 prompt 파일 생성
        prompt = _write(
            tmp_path,
            "prompt.md",
            "## lesson_analysis\n\n📑 본문\n\n---\n",
        )
        # 인자로 깨끗한 파일만 전달 — 기본 prompt/, schemas/, reports/ 가 아닌
        # 이 깨끗한 파일만 검사하므로 결과는 통과여야 함
        clean = _write(tmp_path, "clean_input.txt", "이모지 없음\n")

        rc = main([str(clean)])

        captured = capsys.readouterr()
        assert rc == 0
        assert captured.err == ""
        # 명시 인자의 파일 수만큼만 요약에 반영
        assert "OK: scanned 1 files" in captured.out
        # prompt.md 의 이모지는 검사 대상이 아니어서 보고되지 않음
        assert "📑" not in captured.err

        # 별도로 prompt.md 만 인자로 주면 검출되어야 함을 확인
        rc2 = main([str(prompt)])
        captured2 = capsys.readouterr()
        assert rc2 == 1
        assert "📑" in captured2.err


def test_script_runs_as_cli_subprocess(tmp_path):
    """Regression guard: script must work when invoked directly via
    the Python interpreter, not only when pytest sets up sys.path."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path

    clean_file = tmp_path / "clean.md"
    clean_file.write_text("# Plain title\n\nNo emojis here.\n", encoding="utf-8")

    script = _Path(__file__).resolve().parent.parent.parent / "scripts" / "check_no_emojis_in_reports.py"
    result = subprocess.run(
        [_sys.executable, str(script), str(clean_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}.\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
