"""lessonplan_analysis 라우터의 503 MODEL_OVERLOADED 분기 테스트 (#120)"""
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user, get_db
from app.main import app
from app.models.users import User


@pytest_asyncio.fixture
async def client(tmp_path):
    test_user = User(id=1, username="tester", hashed_password="x")

    async def override_get_user():
        return test_user

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_analyze_returns_503_on_model_overloaded(client):
    """MODEL_OVERLOADED 에러 코드 시 HTTP 503 + Retry-After 헤더 반환"""
    mock_result = {
        "success": False,
        "error": "AI 모델이 일시적으로 혼잡합니다. 잠시 후 다시 시도해주세요.",
        "error_code": "MODEL_OVERLOADED",
    }

    with patch(
        "app.routers.lessonplan_analysis.LessonPlanAnalysisService"
    ) as mock_service:
        instance = mock_service.return_value
        instance.analyze_lesson_plan = AsyncMock(return_value=mock_result)

        res = await client.post(
            "/api/lessonplan/analyze",
            json={"session_id": 1},
        )

    assert res.status_code == 503
    assert res.headers.get("retry-after") == "30"
    assert "혼잡" in res.json()["detail"]
