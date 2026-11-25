"""lessonplan_analysis 라우터의 429 RESOURCE_EXHAUSTED 분기 테스트"""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user, get_db
from app.main import app
from app.models.users import User


@pytest_asyncio.fixture
async def client(tmp_path):
    """get_current_user와 get_db를 오버라이드한 테스트 클라이언트"""
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
async def test_analyze_returns_429_on_resource_exhausted(client):
    """RESOURCE_EXHAUSTED 에러 코드 시 HTTP 429 + Retry-After 헤더 반환"""
    mock_result = {
        "success": False,
        "error": "할당량 초과",
        "error_code": "RESOURCE_EXHAUSTED",
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

    assert res.status_code == 429
    assert res.headers.get("retry-after") == "30"
    assert res.json()["detail"] == "할당량 초과"


@pytest.mark.asyncio
async def test_analyze_returns_500_on_generic_error(client):
    """error_code가 없으면 기존대로 HTTP 500 반환"""
    mock_result = {"success": False, "error": "boom"}

    with patch(
        "app.routers.lessonplan_analysis.LessonPlanAnalysisService"
    ) as mock_service:
        instance = mock_service.return_value
        instance.analyze_lesson_plan = AsyncMock(return_value=mock_result)

        res = await client.post(
            "/api/lessonplan/analyze",
            json={"session_id": 1},
        )

    assert res.status_code == 500
    assert res.json()["detail"] == "boom"


@pytest.mark.asyncio
async def test_analyze_returns_409_on_already_analyzed(client):
    """ALREADY_ANALYZED 에러 코드 시 HTTP 409 + report_id 반환"""
    mock_result = {
        "success": False,
        "error": "이미 분석된 문서입니다.",
        "error_code": "ALREADY_ANALYZED",
        "report_id": 17,
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

    assert res.status_code == 409
    body = res.json()
    assert body["detail"] == "이미 분석된 문서입니다."
    assert body["report_id"] == 17
    assert res.headers.get("x-report-id") == "17"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_code, message",
    [
        (
            "INVALID_REPORT",
            "분석 결과가 올바르게 만들어지지 않았습니다. 다시 시도해주세요.",
        ),
        (
            "LESSONPLAN_NOT_RETRIEVED",
            "업로드한 지도안 내용을 읽지 못했습니다. "
            "지도안을 다시 업로드한 뒤 분석해 주세요.",
        ),
        (
            "LESSONPLAN_INDEX_MISSING",
            "지도안 검색 색인이 없습니다. 지도안을 다시 업로드한 뒤 분석해 주세요.",
        ),
    ],
)
async def test_analyze_returns_500_with_message_on_invalid_report(
    client, error_code, message
):
    """#439: 보고서 검사 실패는 일반 500 분기로 나가고 문구가 그대로 보인다"""
    mock_result = {"success": False, "error_code": error_code, "error": message}

    with patch(
        "app.routers.lessonplan_analysis.LessonPlanAnalysisService"
    ) as mock_service:
        instance = mock_service.return_value
        instance.analyze_lesson_plan = AsyncMock(return_value=mock_result)

        res = await client.post(
            "/api/lessonplan/analyze",
            json={"session_id": 1},
        )

    assert res.status_code == 500
    assert res.json() == {"detail": message}
