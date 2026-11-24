"""#429: 테스트는 앱 시작 DB(DATABASE_URL)를 임시 폴더의 파일로 돌린다."""

import importlib
import os
import tempfile
from pathlib import Path

from app.db import engine


def test_startup_db_is_temp_file_not_dev_db():
    db_path = Path(engine.url.database)
    assert db_path.is_relative_to(tempfile.gettempdir())
    assert db_path != Path("data/app.db").resolve()


def test_database_url_env_matches_engine_after_second_conftest_run():
    # tests.conftest 를 import 하는 테스트 파일처럼 conftest 본문을 한 번 더 실행시킨다
    importlib.import_module("tests.conftest")
    assert os.environ["DATABASE_URL"] == str(engine.url)
