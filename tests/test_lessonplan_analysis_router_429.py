"""lessonplan_analysis 라우터의 429 RESOURCE_EXHAUSTED 분기 테스트"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.dependencies import get_current_user, get_db
from app.models.users import User


@pytest_asyncio.fixture
async def client(tmp_path):
    """get_current_user와 get_db를 오버라이드한 테스트 클라이언트"""
    test_user = User(
        id=1, username="tester", email="t@t.com", hashed_password="x"
    )

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
async def test_analyze_returns_429_on_resource_exhausted(client):
    """RESOURCE_EXHAUSTED 에러 코드 시 HTTP 429 반환

    NOTE: 라우터는 HTTPException(headers={"Retry-After": "30"})을 발생시키지만,
    app/main.py의 커스텀 예외 핸들러가 JSONResponse를 새로 만들 때
    exc.headers를 전달하지 않아 Retry-After 헤더가 소실됨.
    헤더 전파는 별도 수정 필요.
    """
    mock_result = {
        "success": False,
        "error": "할당량 초과",
        "error_code": "RESOURCE_EXHAUSTED",
    }

    with patch(
        "app.routers.lessonplan_analysis.LessonPlanAnalysisService"
    ) as MockService:
        instance = MockService.return_value
        instance.analyze_lesson_plan = AsyncMock(return_value=mock_result)

        res = await client.post(
            "/api/lessonplan/analyze",
            json={"session_id": 1},
        )

    assert res.status_code == 429
    assert res.json()["detail"] == "할당량 초과"


@pytest.mark.asyncio
async def test_analyze_returns_500_on_generic_error(client):
    """error_code가 없으면 기존대로 HTTP 500 반환"""
    mock_result = {"success": False, "error": "boom"}

    with patch(
        "app.routers.lessonplan_analysis.LessonPlanAnalysisService"
    ) as MockService:
        instance = MockService.return_value
        instance.analyze_lesson_plan = AsyncMock(return_value=mock_result)

        res = await client.post(
            "/api/lessonplan/analyze",
            json={"session_id": 1},
        )

    assert res.status_code == 500
    assert res.json()["detail"] == "boom"
