"""
scripts/ci_ratchet.py 판정 로직 단위 테스트

pytest 를 실제로 돌리지 않고 순수 함수만 검증한다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci_ratchet.py"
_spec = importlib.util.spec_from_file_location("ci_ratchet", SCRIPT_PATH)
ratchet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ratchet)

PYTEST_OUTPUT = """\
..F.....E..
ERROR    app.services.qna_service:qna_service.py:120 Gemini 호출 실패
FAILED   app.something - 로그 줄도 제외
=========================== short test summary info ============================
FAILED tests/test_a.py::test_x - AssertionError: assert 1 == 2
FAILED tests/unit/test_b.py::TestC::test_y[case-1] - KeyError: 'k'
ERROR tests/test_dashboard_view.py::test_view - RuntimeError: boom
ERROR tests/unit/test_criteria_delete.py
ERROR tests/integration/test_qna_api.py - ModuleNotFoundError: No module
37 failed, 25 errors, 979 passed in 120.00s
"""


def test_parse_failures_keeps_summary_lines_only():
    assert ratchet.parse_failures(PYTEST_OUTPUT.splitlines(True)) == {
        "FAILED tests/test_a.py::test_x",
        "FAILED tests/unit/test_b.py::TestC::test_y[case-1]",
        "ERROR tests/test_dashboard_view.py::test_view",
        "ERROR tests/unit/test_criteria_delete.py",
        "ERROR tests/integration/test_qna_api.py",
    }


def test_read_known_skips_comments_and_blank_lines():
    text = "# 헤더\n#\n\nFAILED tests/a.py::t\n  \nERROR tests/b.py\n"
    assert ratchet.read_known(text) == {
        "FAILED tests/a.py::t",
        "ERROR tests/b.py",
    }


def test_render_known_keeps_header_and_sorts():
    old = "# 헤더 1\n# 헤더 2\nFAILED tests/old.py::t\n"
    actual = {"FAILED tests/z.py::t", "ERROR tests/a.py"}
    assert ratchet.render_known(old, actual) == (
        "# 헤더 1\n# 헤더 2\nERROR tests/a.py\nFAILED tests/z.py::t\n"
    )


def test_compare_reports_new_and_fixed():
    known = {"FAILED tests/a.py::t", "ERROR tests/b.py"}
    actual = {"FAILED tests/a.py::t", "FAILED tests/c.py::t"}
    assert ratchet.compare(actual, known) == (
        {"FAILED tests/c.py::t"},
        {"ERROR tests/b.py"},
    )
    assert ratchet.compare(known, known) == (set(), set())
