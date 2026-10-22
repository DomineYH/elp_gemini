"""Regression coverage for refreshing the report list after analysis."""

from pathlib import Path

from tests.test_dashboard_history_xss import _extract_js_function

DASHBOARD_TEMPLATE = Path("app/templates/user/dashboard.html")


def test_start_analysis_refreshes_report_list_on_success():
    source = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    body = _extract_js_function(source, "startAnalysis")
    success = body[body.index("if (data.success) {") :]
    success = success[: success.index("} else {")]

    lines = [line.strip() for line in success.splitlines() if line.strip()]
    show_index = lines.index("showAnalysisResult(data.report);")
    assert lines[show_index + 1 : show_index + 2] == ["loadReportList();"]
