"""지도안 분석 API 500 detail에 내부 예외 문구가 새지 않는지 확인 (#225)"""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from google.api_core import exceptions
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user, get_db
from app.main import app
from app.models.users import User
from app.services.lessonplan_analysis_service import LessonPlanAnalysisService

INTERNAL = "fileSearchStores/user3store-abc/documents/x"


@pytest_asyncio.fixture
async def client():
    """get_current_user와 get_db를 오버라이드한 테스트 클라이언트

    get_db 세션의 execute는 내부 문구를 담은 예외를 던진다.
    """
    test_user = User(id=1, username="tester", hashed_password="x")

    async def override_get_user():
        return test_user

    async def override_get_db():
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError(INTERNAL))
        yield db

    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_analyze_500_hides_internal_detail(client):
    with patch(
        "app.routers.lessonplan_analysis.LessonPlanAnalysisService"
    ) as mock_service:
        instance = mock_service.return_value
        instance.analyze_lesson_plan = AsyncMock(
            side_effect=RuntimeError(INTERNAL)
        )

        res = await client.post(
            "/api/lessonplan/analyze",
            json={"session_id": 1},
        )

    assert res.status_code == 500
    detail = res.json()["detail"]
    assert "fileSearchStores" not in detail
    assert detail == "분석 중 오류가 발생했습니다."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path, expected",
    [
        ("/api/lessonplan/reports", "보고서 목록을 불러오지 못했습니다."),
        ("/api/lessonplan/reports/1", "보고서를 불러오지 못했습니다."),
        (
            "/api/lessonplan/reports/1/download",
            "보고서를 다운로드하지 못했습니다.",
        ),
    ],
    ids=["list", "get", "download"],
)
async def test_report_routes_500_hide_internal_detail(client, path, expected):
    res = await client.get(path)

    assert res.status_code == 500
    detail = res.json()["detail"]
    assert "fileSearchStores" not in detail
    assert detail == expected


@pytest.mark.asyncio
async def test_service_google_api_error_hides_internal_detail():
    service = LessonPlanAnalysisService(db=AsyncMock())
    service._find_existing_report_for_latest_upload = AsyncMock(
        side_effect=exceptions.GoogleAPIError(INTERNAL)
    )

    result = await service.analyze_lesson_plan(session_id=1, user_id=1)

    assert result["success"] is False
    assert "fileSearchStores" not in result["error"]
