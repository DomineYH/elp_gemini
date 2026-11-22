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


def _classes(source: str) -> list[set[str]]:
    return [set(c.split()) for c in re.findall(r'class="([^"]*)"', source)]


def test_narrow_layout_classes_in_templates_and_css():
    """#390: 좁은 폭에서 헤더는 항목 단위로 줄바꿈, 입력줄은 입력칸 한 줄 + 버튼 아랫줄."""
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    sim = (TEMPLATES / "user" / "simulation.html").read_text(encoding="utf-8")

    nav, container = _classes(base[base.index("<nav") :])[:2]
    links = _classes(base[: base.index("{% block nav_links %}")])[-1]
    assert "break-keep" in nav
    assert {"flex", "flex-wrap", "gap-x-4", "gap-y-2"} <= container
    assert {
        "flex",
        "flex-wrap",
        "items-center",
        "justify-end",
        "gap-x-4",
        "gap-y-1",
        "ml-auto",
        "whitespace-nowrap",
    } <= links
    assert {"flex-wrap", "justify-end"} <= _classes(
        sim[sim.index('id="tForm"') :]
    )[0]
    tinput = _classes(sim[sim.index('id="tInput"') :])[0]
    assert {"w-full", "sm:w-auto", "sm:flex-1", "min-w-0"} <= tinput
    assert "flex-1" not in tinput
    # 640px 미만은 두 줄 입력줄 + 재시도 카드가 마지막 기록을 가리지 않게 여백을 더 둔다
    assert {"pb-40", "sm:pb-28"} <= _classes(
        sim[sim.index("{% block content %}") :]
    )[0]

    css = CSS_PATH.read_text(encoding="utf-8")
    for selector in (
        ".break-keep",
        ".gap-x-4",
        ".gap-y-2",
        ".gap-y-1",
        ".sm\\:w-auto",
        ".sm\\:flex-1",
        ".pb-40",
        ".sm\\:pb-28",
    ):
        assert (
            selector in css
        ), f"scripts/build_tailwind.sh 재실행 필요: {selector}"
    sm_rules = "".join(
        re.findall(
            r"@media \(min-width:640px\)\{((?:[^{}]*\{[^{}]*\})*)\}", css
        )
    )
    for rule in (
        ".sm\\:w-auto{width:auto}",
        ".sm\\:flex-1{flex:1 1 0%}",
        ".sm\\:pb-28{padding-bottom:7rem}",
    ):
        assert rule in sm_rules, f"640px 미디어 쿼리 밖이거나 없음: {rule}"
