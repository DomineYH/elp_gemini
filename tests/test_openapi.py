"""/openapi.json 스키마 직렬화와 DEBUG 전용 노출 (#267)."""

import json

from fastapi.testclient import TestClient


def test_openapi_schema_is_serializable():
    from app.main import app

    app.openapi_schema = None  # 다른 테스트가 캐시해 둔 스키마를 버린다
    schema = app.openapi()
    json.dumps(schema)
    assert "/api/lessonplan/analyze" in schema["paths"]


def test_openapi_url_follows_debug():
    import app.main as main_mod

    # 앱은 import 시 1회 생성되므로 FastAPI 인자 규칙만 검사한다
    expected = "/openapi.json" if main_mod.settings.DEBUG else None
    assert main_mod.app.openapi_url == expected
    res = TestClient(main_mod.app).get("/openapi.json")
    assert res.status_code == (200 if main_mod.settings.DEBUG else 404)
