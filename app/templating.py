"""
공통 템플릿 설정
Jinja2Templates 인스턴스와 전역 값을 한 곳에서 관리
"""
import subprocess

from fastapi.templating import Jinja2Templates


templates = Jinja2Templates(directory="app/templates")


def _app_version() -> str:
    try:
        count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return f"v2.{count}"
    except Exception:
        return "v2"


templates.env.globals["app_version"] = _app_version()
