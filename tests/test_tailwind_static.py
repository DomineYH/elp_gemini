"""#268 item 1: Tailwind CDN 대신 미리 빌드한 CSS를 /static/css 로 제공."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

CSS_PATH = Path("app/static/css/tailwind.css")
TEMPLATES = Path("app/templates")
# 좁은 패턴만 검사해 flaky 하지 않게 한다 (색상 유틸리티 재생성 누락 감지)
COLOR_CLASS_RE = re.compile(
    r"^(bg|text|border)-(gray|blue|red|green|yellow|purple|indigo)-\d{2,3}$"
)


def test_tailwind_css_served_unauthenticated():
    response = TestClient(app).get("/static/css/tailwind.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert ".prose" in response.text
    assert ".bg-gray-50" in response.text


def test_base_template_does_not_use_tailwind_cdn():
    source = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert "cdn.tailwindcss.com" not in source
    assert 'href="/static/css/tailwind.css"' in source


def test_built_css_contains_template_color_classes():
    css = CSS_PATH.read_text(encoding="utf-8")
    tokens = {
        token
        for path in TEMPLATES.rglob("*.html")
        for token in re.split(r"[\s\"'`]+", path.read_text(encoding="utf-8"))
        if COLOR_CLASS_RE.match(token)
    }

    missing = sorted(t for t in tokens if f".{t}" not in css)
    assert tokens
    assert not missing, f"scripts/build_tailwind.sh 재실행 필요: {missing}"
