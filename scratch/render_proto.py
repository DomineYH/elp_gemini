"""PROTOTYPE (#140): render the throwaway simulation templates to static HTML without the server.
Run from repo root: python scratch/render_proto.py  ->  scratch/out/*.html"""
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
env = Environment(loader=FileSystemLoader(ROOT / "app/templates"))
request = SimpleNamespace(session={"user_id": 1, "nickname": "테스트", "is_admin": False})
out = ROOT / "scratch/out"
out.mkdir(exist_ok=True)
for name in ("simulation_setup", "simulation"):
    html = env.get_template(f"user/{name}.html").render(request=request, app_version="proto")
    # self-check: extended base.html (nav rendered) and no raw jinja left
    assert "{%" not in html and "AI기반 수업설계 피드백 시스템" in html and "테스트님" in html, name
    (out / f"{name}.html").write_text(html, encoding="utf-8")
    print("wrote", out / f"{name}.html")
