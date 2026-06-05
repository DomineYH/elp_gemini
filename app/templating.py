"""
공통 템플릿 설정
Jinja2Templates 인스턴스와 전역 값을 한 곳에서 관리
"""
import os
import shutil
import subprocess
from pathlib import Path

from fastapi.templating import Jinja2Templates


templates = Jinja2Templates(directory="app/templates")
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SYSTEM_PATHS = ("/usr/bin", "/usr/local/bin", "/bin")


def _app_version() -> str:
    """환경 변수 또는 git 커밋 수로 앱 버전을 계산한다."""
    app_version = os.environ.get("APP_VERSION")
    if app_version:
        return app_version

    try:
        current_path = os.environ.get("PATH", "")
        git_path = os.pathsep.join(
            path for path in (current_path, *_SYSTEM_PATHS) if path
        )
        git = shutil.which("git", path=git_path)
        if git is None:
            for candidate in ("/usr/bin/git", "/usr/local/bin/git", "/bin/git"):
                if Path(candidate).is_file() and os.access(candidate, os.X_OK):
                    git = candidate
                    break
        if git is None:
            git = "git"

        count = subprocess.run(
            [git, "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True,
            cwd=_REPO_ROOT,
            env={**os.environ, "PATH": git_path},
        ).stdout.strip()
        return f"v2.{count}"
    except Exception:
        return "v2"


templates.env.globals["app_version"] = _app_version()
