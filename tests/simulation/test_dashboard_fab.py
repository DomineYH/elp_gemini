"""대시보드 FAB 3번째 버튼과 모바일 라벨 숨김 (#151)."""

import re
from datetime import datetime
from types import SimpleNamespace

from app.templating import templates


def _render():
    request = SimpleNamespace(
        session={"user_id": 1}, url=SimpleNamespace(path="/dashboard")
    )
    return templates.get_template("user/dashboard.html").render(
        request=request,
        user=SimpleNamespace(username="t", nickname="t", is_admin=False),
        document={
            "id": "doc-1",
            "title": "plan.pdf",
            "status": "ready",
            "uploaded_at": datetime(2026, 10, 21),
            "file_size": 1024,
            "content": "text",
            "store_id": "s",
            "file_url": "/static/uploads/1/plan.pdf",
        },
        extracted_text="text",
        criteria_documents=[],
    )


def _fab_block(html):
    start = html.index("<!-- Floating Action Buttons -->")
    return html[start : html.index("<!-- Chatbot Modal -->", start)]


def test_fab_has_three_controls_with_simulation_link():
    fab = _fab_block(_render())
    controls = re.findall(r"<(button|a)\b[^>]*aria-label=", fab)
    assert len(controls) == 3
    assert 'href="/simulation/setup"' in fab
    assert 'onclick="toggleChatbot()"' in fab
    assert 'onclick="startAnalysis()"' in fab
    assert "수업 시뮬레이션" in fab


def test_fab_labels_hidden_on_mobile():
    fab = _fab_block(_render())
    labels = re.findall(r'<span class="([^"]*)">([^<]+)</span>', fab)
    assert [text for _, text in labels] == [
        "QnA 챗봇",
        "분석 시작",
        "수업 시뮬레이션",
    ]
    assert all("hidden sm:inline" in cls for cls, _ in labels)
    assert "space-x-4" not in fab
