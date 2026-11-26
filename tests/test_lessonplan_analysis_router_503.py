"""lessonplan_analysis 라우터의 503 MODEL_OVERLOADED 분기 테스트 (#120)"""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from google.genai import errors as genai_errors
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.main import app
from app.models.users import User
from app.services import lessonplan_analysis_service as svc_mod
from app.services.criteria_vector_service import CriteriaVectorService
from app.services.file_search_service import FileSearchService
from app.services.lessonplan_analysis_service import LessonPlanAnalysisService


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


# 스토어 조회 실패가 '분석할 문서가 없습니다'가 아니라 재시도 안내로 나간다 (#464)
UPLOAD = SimpleNamespace(
    id=27,
    fs_document_id="fileSearchStores/u/documents/d",
    filename="a.pdf",
    original_filename="lessonplan_ko.pdf",
)
DELAYED = "AI 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요."


def _store(display_name, name):
    store = MagicMock(display_name=display_name)
    store.name = name
    return store


STORES = [
    _store(settings.FS_RUBRIC_STORE_NAME, "fileSearchStores/r"),
    _store("user-1-store", "fileSearchStores/u"),
]


@pytest.fixture
def analyze(client, monkeypatch):
    """(응답, list 호출 수, generate 호출 수, 응답 뒤 in_progress)를 돌려준다."""
    monkeypatch.setattr(time, "sleep", lambda s: None)

    async def run(list_effect):
        fake = MagicMock()
        fake.file_search_stores.list.side_effect = list_effect
        generate = MagicMock(return_value=None)
        with (
            patch.object(FileSearchService, "_client", fake),
            patch.object(
                LessonPlanAnalysisService,
                "_find_existing_report_for_latest_upload",
                AsyncMock(return_value=(UPLOAD, None)),
            ),
            patch.object(
                CriteriaVectorService,
                "active_stable_id_filter",
                AsyncMock(return_value='stable_id="A"'),
            ),
            patch.object(svc_mod, "_call_gemini_with_file_search", generate),
        ):
            res = await client.post(
                "/api/lessonplan/analyze", json={"session_id": 1}
            )
            status = await client.get("/api/lessonplan/analyze/status")
        return (
            res,
            fake.file_search_stores.list.call_count,
            generate.call_count,
            status.json()["in_progress"],
        )

    return run


def _raising(make):
    def _list(**kwargs):
        raise make()

    return _list


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make",
    [
        lambda: httpx.ReadTimeout("The read operation timed out"),
        lambda: httpx.RemoteProtocolError("Server disconnected"),
    ],
)
async def test_store_lookup_transport_failure_is_503_retry_later(analyze, make):
    res, lists, generates, in_progress = await analyze(_raising(make))

    assert res.status_code == 503, res.text
    assert res.headers["retry-after"] == "30"
    assert res.json()["detail"] == DELAYED
    assert (lists, generates, in_progress) == (3, 0, False)


@pytest.mark.asyncio
async def test_store_lookup_sdk_503_keeps_overloaded_contract(analyze):
    res, lists, generates, in_progress = await analyze(
        _raising(
            lambda: genai_errors.ServerError(503, {"error": {"code": 503}})
        )
    )

    assert res.status_code == 503, res.text
    assert res.headers["retry-after"] == "30"
    assert "혼잡" in res.json()["detail"]
    assert (lists, generates, in_progress) == (3, 0, False)


@pytest.mark.asyncio
async def test_store_lookup_sdk_429_keeps_quota_contract(analyze):
    res, lists, generates, in_progress = await analyze(
        _raising(
            lambda: genai_errors.ClientError(429, {"error": {"code": 429}})
        )
    )

    assert res.status_code == 429, res.text
    assert res.headers["retry-after"] == "30"
    assert "요청량" in res.json()["detail"]
    assert (lists, generates, in_progress) == (3, 0, False)


@pytest.mark.asyncio
async def test_store_lookup_timeout_once_then_analysis_goes_on(analyze):
    effect = [httpx.ReadTimeout("The read operation timed out"), STORES]
    res, lists, generates, in_progress = await analyze(effect)

    assert lists == 2
    assert generates > 0
    assert "분석할 문서가 없습니다" not in res.text
    assert in_progress is False


@pytest.mark.asyncio
async def test_missing_rubric_store_says_so(analyze):
    res, lists, generates, in_progress = await analyze(
        lambda **kwargs: [STORES[1]]
    )

    assert res.status_code == 500, res.text
    assert res.json()["detail"] == (
        "평가기준 스토어를 찾을 수 없습니다. 관리자에게 문의하세요."
    )
    assert (generates, in_progress) == (0, False)
