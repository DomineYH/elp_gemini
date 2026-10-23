"""#262: DEBUG가 꺼진 운영 모드에서도 startup이 빈 DB에 테이블을 만든다."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

CORE_TABLES = (
    "users",
    "criteria",
    "chat_sessions",
    "chat_messages",
    "analysis_reports",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("env_password", [None, "EnvAdmin2026"])
async def test_startup_creates_core_tables_without_debug(
    tmp_path, monkeypatch, env_password
):
    import app.main as main_mod

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    monkeypatch.setattr(main_mod, "engine", eng)
    monkeypatch.setattr(main_mod.settings, "DEBUG", False)
    monkeypatch.setattr(
        main_mod.settings, "ADMIN_INITIAL_PASSWORD", env_password
    )
    monkeypatch.setattr(
        main_mod.settings, "CRITERIA_CLOUD_RECONCILE_ENABLED", False
    )
    try:
        with patch("app.db.seed_initial_data") as seed:
            for _ in range(2):  # 재실행 멱등
                await main_mod.startup_event()
                async with eng.begin() as conn:
                    has = await conn.run_sync(
                        lambda c: {
                            t: inspect(c).has_table(t) for t in CORE_TABLES
                        }
                    )
                assert all(has.values()), has
        # 운영 모드: 환경변수가 있을 때만 그 값으로 시드한다 (#264)
        if env_password:
            seed.assert_called_with(env_password)
        else:
            seed.assert_not_called()
    finally:
        await eng.dispose()


# conftest가 app.main을 먼저 import해 metadata가 이미 차 있으므로 새 인터프리터에서 검사
STANDALONE_CODE = """
import asyncio, sys
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from app.db import create_tables

async def main():
    eng = create_async_engine("sqlite+aiosqlite:///" + sys.argv[1])
    try:
        await create_tables(eng)
        async with eng.begin() as conn:
            names = await conn.run_sync(lambda c: inspect(c).get_table_names())
    finally:
        await eng.dispose()
    print("TABLES:" + ",".join(names))

asyncio.run(main())
"""


def test_create_tables_standalone_builds_all_tables(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "TYPESAFE_API_KEY"}
    res = subprocess.run(
        [sys.executable, "-c", STANDALONE_CODE, str(tmp_path / "fresh.db")],
        env=env,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    line = res.stdout.split("TABLES:")[-1].strip()
    names = line.split(",") if line else []
    assert len(names) == 13, names
    assert "simulation_sessions" in names
