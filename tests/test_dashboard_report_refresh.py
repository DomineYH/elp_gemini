"""Regression coverage for refreshing the report list after analysis."""

import json
from pathlib import Path

from tests.test_dashboard_history_xss import (
    _extract_js_function,
    _run_node_script,
)

DASHBOARD_TEMPLATE = Path("app/templates/user/dashboard.html")


def test_start_analysis_refreshes_report_list_on_success():
    source = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    body = _extract_js_function(source, "startAnalysis")
    success = body[body.index("if (data.success) {") :]
    success = success[: success.index("} else {")]

    lines = [line.strip() for line in success.splitlines() if line.strip()]
    show_index = lines.index("showAnalysisResult(data.report);")
    assert lines[show_index + 1 : show_index + 2] == ["loadReportList();"]


# --- #442: 새로고침 뒤 '분석 중' 오버레이 복원 ---

REPORTS_URL = "/api/lessonplan/reports"
STATUS_URL = "/api/lessonplan/analyze/status"


def _run_resume(script: str, answers: str):
    """resumeAnalysisIfRunning을 대역 fetch로 돌린다.

    answers: URL → 차례로 돌려줄 값의 배열(JS 객체 리터럴). 값이 숫자면 그 HTTP
    상태의 실패 응답, 'throw'면 네트워크 오류. 마지막 값은 되풀이된다.
    """
    source = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    # _extract_js_function은 'function'부터 자르므로 async를 다시 붙인다
    functions = "\n".join(
        "async " + _extract_js_function(source, name)
        for name in ("fetchAnalysisJson", "resumeAnalysisIfRunning")
    )
    _run_node_script(
        f"""
        const assert = require('node:assert/strict');
        const answers = {answers};
        const log = [];
        const fetched = [];
        global.setTimeout = (fn, ms) => {{ log.push(['wait', ms]); setImmediate(fn); }};
        global.fetch = async (url) => {{
            fetched.push(url);
            const queue = answers[url];
            const value = queue.length > 1 ? queue.shift() : queue[0];
            if (value === 'throw') throw new Error('network');
            if (typeof value === 'number') return {{ ok: false, status: value }};
            return {{ ok: true, status: 200, json: async () => value }};
        }};
        const button = {{disabled: true}};
        global.document = {{getElementById: () => button}};
        function setHistoryListState() {{log.push(['list-error']);}}
        global.alert = (message) => log.push(['alert', message]);
        function setAnalysisOverlay(visible) {{ log.push(['overlay', visible]); }}
        function renderReportList(reports) {{ log.push(['list', reports.map(r => r.id)]); }}
        function showAnalysisResult(content) {{ log.push(['show', content]); }}
        {functions}
        (async () => {{
            await resumeAnalysisIfRunning();
            assert.equal(button.disabled, false);
            const initial = log.shift();
            assert.ok(['list', 'list-error'].includes(initial[0]));
            const events = log.filter(entry => entry[0] !== 'wait');
            const waits = log.filter(entry => entry[0] === 'wait');
            {script}
        }})().catch(error => {{ console.error(error); process.exit(1); }});
        """
    )


def test_resume_does_nothing_when_no_analysis_is_running():
    _run_resume(
        """
        assert.deepEqual(events, []);
        assert.deepEqual(fetched, ['/api/lessonplan/reports', '/api/lessonplan/analyze/status']);
        """,
        f"{{'{REPORTS_URL}': [{{reports: [{{id: 3}}]}}],"
        f" '{STATUS_URL}': [{{in_progress: false}}]}}",
    )


def test_resume_does_nothing_when_first_status_call_fails():
    for failure in ("500", "401", "'throw'"):
        _run_resume(
            "assert.deepEqual(events, []);",
            f"{{'{REPORTS_URL}': [{{reports: []}}],"
            f" '{STATUS_URL}': [{failure}]}}",
        )


def test_resume_shows_overlay_then_opens_the_new_report():
    _run_resume(
        """
        assert.deepEqual(events, [
            ['overlay', true],
            ['overlay', false],
            ['list', [4, 3]],
            ['show', '# 새 보고서'],
        ]);
        assert.deepEqual(waits, [['wait', 3000], ['wait', 3000]]);
        """,
        f"{{'{REPORTS_URL}': [{{reports: [{{id: 3}}]}}, {{reports: [{{id: 4}}, {{id: 3}}]}}],"
        f" '{STATUS_URL}': [{{in_progress: true}}, {{in_progress: true}}, {{in_progress: false}}],"
        f" '{REPORTS_URL}/4': [{{content: '# 새 보고서'}}]}}",
    )


def test_resume_reports_unfinished_analysis_when_no_new_report():
    _run_resume(
        """
        assert.deepEqual(events, [
            ['overlay', true],
            ['overlay', false],
            ['list', [3]],
            ['alert', '분석이 끝나지 않았습니다. 다시 시도해 주세요.'],
        ]);
        """,
        f"{{'{REPORTS_URL}': [{{reports: [{{id: 3}}]}}],"
        f" '{STATUS_URL}': [{{in_progress: true}}, {{in_progress: false}}]}}",
    )


def test_resume_survives_two_failed_status_calls():
    _run_resume(
        """
        assert.deepEqual(events.map(entry => entry[0]), ['overlay', 'overlay', 'list', 'alert']);
        assert.equal(waits.length, 3);
        """,
        f"{{'{REPORTS_URL}': [{{reports: []}}],"
        f" '{STATUS_URL}': [{{in_progress: true}}, 500, 'throw', {{in_progress: false}}]}}",
    )


def test_resume_stops_after_three_failed_status_calls():
    _run_resume(
        """
        assert.deepEqual(events, [
            ['overlay', true],
            ['overlay', false],
            ['alert', '분석 상태를 확인할 수 없습니다. 페이지를 새로고침해 주세요.'],
        ]);
        assert.equal(waits.length, 3);
        """,
        f"{{'{REPORTS_URL}': [{{reports: []}}],"
        f" '{STATUS_URL}': [{{in_progress: true}}, 401]}}",
    )


def test_resume_stops_at_the_poll_limit():
    _run_resume(
        """
        assert.equal(waits.length, 100);
        assert.deepEqual(events.map(entry => entry[0]), ['overlay', 'overlay', 'alert']);
        """,
        f"{{'{REPORTS_URL}': [{{reports: []}}],"
        f" '{STATUS_URL}': [{{in_progress: true}}]}}",
    )


def test_dashboard_resumes_on_load_and_blocks_start_while_overlay_is_up():
    source = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    start = _extract_js_function(source, "startAnalysis")
    resume = _extract_js_function(source, "resumeAnalysisIfRunning")
    overlay = _extract_js_function(source, "setAnalysisOverlay")

    # 페이지를 열 때 한 번 부른다 (정의 밖의 호출)
    outside = source.replace(resume, "").replace(start, "")
    assert outside.count("resumeAnalysisIfRunning(),") == 1
    # 오버레이가 떠 있으면(분석 중 포함) 키보드로도 다시 시작할 수 없다
    guard = "if (!loadingOverlay.classList.contains('hidden')) return;"
    assert guard in start
    assert start.index(guard) < start.index("fetch(")
    # 지운 지역 변수를 쓰는 줄이 남으면 분석이 끝날 때 ReferenceError가 난다
    assert "loadingText" not in start and "loadingDesc" not in start
    assert "수업 지도안 분석 중..." in overlay
    assert "cache: 'no-store'" in _extract_js_function(
        source, "fetchAnalysisJson"
    )


def test_dashboard_script_block_still_parses():
    """손댄 함수의 문법 오류는 같은 블록의 업로드·챗봇 스크립트까지 멈춘다"""
    source = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    start = source.rindex("<script>") + len("<script>")
    script = source[start : source.rindex("</script>")]
    # 블록 안의 Jinja는 문자열 리터럴 안의 {{ }} 하나뿐이라 그대로 JS로 읽힌다
    _run_node_script(f"new Function({json.dumps(script, ensure_ascii=False)});")


def test_failed_baseline_never_opens_an_old_report():
    _run_resume(
        """
        assert.deepEqual(events.map(entry => entry[0]), ['overlay','overlay','list','alert']);
        assert.deepEqual(events[2][1], [3]);
        """,
        f"{{'{REPORTS_URL}': [500, {{reports: [{{id: 3}}]}}],"
        f" '{STATUS_URL}': [{{in_progress: true}}, {{in_progress: false}}]}}",
    )


def test_analysis_button_blocks_keyboard_during_initial_check_and_poll():
    source = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    assert (
        '<button id="analysisStart" disabled onclick="startAnalysis()"'
        in source
    )
    start = "async " + _extract_js_function(source, "startAnalysis")
    overlay = _extract_js_function(source, "setAnalysisOverlay")
    _run_node_script(
        """
        const assert = require('node:assert/strict');
        const button = { disabled: true };
        const document = { getElementById: () => button };
        let hidden = true;
        const loadingOverlay = {
          querySelector: () => ({}),
          classList: {contains: () => hidden, toggle: (_, hide) => {hidden = hide;}},
        };
        let calls = 0;
        global.fetch = () => {calls++; throw Error('unexpected post');};
        global.alert = () => {};
        """
        + start
        + overlay
        + """
        (async () => {
            await startAnalysis();
            assert.equal(calls, 0);
            setAnalysisOverlay(true);
            assert.equal(button.disabled, true);
            assert.equal(hidden, false);
            await startAnalysis();
            assert.equal(calls, 0);
            setAnalysisOverlay(false);
            assert.equal(button.disabled, false);
            assert.equal(hidden, true);
        })().catch(e => {console.error(e); process.exit(1);});
        """
    )
