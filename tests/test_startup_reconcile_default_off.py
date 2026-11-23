# tests/test_startup_reconcile_default_off.py
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_app_start_skips_reconcile_under_default_test_settings():
    # 시작 reconcile 이 시작 DB 쓰기 잠금을 다음 테스트로 흘리지 않게 테스트에서는 끈다 (#424)
    with patch("app.main._run_criteria_reconcile_in_background") as run:
        with TestClient(app):
            pass
    run.assert_not_called()
