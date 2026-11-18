"""QnA·평가·File Search의 generate_content만 일시 오류에 다시 부른다 (#372)"""

import time
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from google.genai import errors as genai_errors
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import Base, get_db
from app.dependencies import get_current_user
from app.models.chat_messages import ChatMessage
from app.models.chat_sessions import ChatSession
from app.models.users import User
from app.routers import evaluations, qna
from app.services.criteria_vector_service import CriteriaVectorService
from app.services.eval_service import EvaluationService
from app.services.file_search_service import FileSearchService
from app.services.lessonplan_analysis_service import (
    _LESSONPLAN_RETRIEVE_QUERY,
)
from tests.test_qna_session_title import (
    DOC,
    SessionLocal,
    engine,
    override_get_db,
)


def _api_error(cls, code):
    return cls(code, {"error": {"code": code, "message": "x"}}, MagicMock())


def _429():
    return _api_error(genai_errors.ClientError, 429)


def _503():
    return _api_error(genai_errors.ServerError, 503)


def _dropped():
    return httpx.RemoteProtocolError("Server disconnected")


TRANSIENT = [_429, _503, _dropped]
NOT_RETRIED = [
    lambda: httpx.ReadTimeout("timed out"),
    lambda: _api_error(genai_errors.ClientError, 400),
    lambda: _api_error(genai_errors.ClientError, 403),
]


class FakeModels:
    """단계마다 넣어 둔 오류를 차례로 던지고, 그 뒤엔 응답을 준다."""

    def __init__(self, stage_of, errors):
        self.stage_of = stage_of
        self.errors = {k: list(v) for k, v in errors.items()}
        self.calls = Counter()
        self.configs = {}

    def generate_content(self, *, model, contents, config):
        stage = self.stage_of(contents, config)
        self.calls[stage] += 1
        self.configs[stage] = config
        if self.errors.get(stage):
            raise self.errors[stage].pop(0)
        return SimpleNamespace(text=f"{stage} 답변", candidates=[])


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)


# --- QnA: 문서 대화 경로 (1패스 지도안 조회 + 최종 답변) ---------------------


def _qna_stage(contents, config):
    return "pass1" if contents == _LESSONPLAN_RETRIEVE_QUERY else "final"


@pytest_asyncio.fixture
async def user():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        row = User(
            username="retry_user",
            nickname="Retry User",
            hashed_password="hashed",
            is_admin=False,
        )
        db.add(row)
        await db.commit()
    yield row
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def ask(user):
    """errors를 넣은 가짜 SDK로 평가성 질문을 한 번 하고 (응답, models, store)."""
    test_app = FastAPI()
    test_app.include_router(qna.router)
    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_current_user] = lambda: user

    async def _ask(**errors):
        models = FakeModels(_qna_stage, errors)
        with (
            patch(
                "app.services.qna_service.genai.Client",
                return_value=SimpleNamespace(models=models),
            ),
            patch("app.services.qna_service.FileSearchService") as fs_cls,
            patch("app.services.qna_service.PromptLoaderService") as pl_cls,
            patch(
                "app.services.criteria_context_service."
                "build_criteria_context_or_notice",
                AsyncMock(return_value=(None, None)),
            ),
            patch.object(
                CriteriaVectorService,
                "active_stable_id_filter",
                AsyncMock(return_value='stable_id="A"'),
            ),
        ):
            store = fs_cls.return_value
            store.get_dual_store_ids = Mock(
                return_value=["fileSearchStores/u", "fileSearchStores/r"]
            )
            pl_cls.return_value.get_prompt = Mock(return_value="system")
            async with AsyncClient(
                transport=ASGITransport(app=test_app),
                base_url="http://testserver",
            ) as client:
                response = await client.post(
                    f"/api/qna/{DOC}", json={"question": "이 수업을 평가해줘"}
                )
        return response, models, store

    return _ask


async def _rows(model):
    async with SessionLocal() as db:
        return (await db.execute(select(model))).scalars().all()


@pytest.mark.asyncio
async def test_qna_first_responses_call_each_stage_once(ask):
    response, models, _ = await ask()

    assert response.status_code == 200, response.text
    assert models.calls == {"pass1": 1, "final": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["pass1", "final"])
@pytest.mark.parametrize("error", TRANSIENT)
async def test_qna_transient_error_once_is_retried(ask, stage, error):
    response, models, store = await ask(**{stage: [error()]})

    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "final 답변"
    other = "final" if stage == "pass1" else "pass1"
    assert models.calls == {stage: 2, other: 1}
    # 재시도는 앞선 스토어 조회·세션 생성을 다시 하지 않는다
    store.get_dual_store_ids.assert_called_once()
    assert len(await _rows(ChatSession)) == 1
    assert len(await _rows(ChatMessage)) == 2


@pytest.mark.asyncio
async def test_qna_pass1_exhausted_falls_back_to_dual_tools(ask):
    response, models, _ = await ask(pass1=[_429(), _429(), _429()])

    assert response.status_code == 200, response.text
    assert models.calls == {"pass1": 3, "final": 1}
    assert len(models.configs["final"].tools) == 2


@pytest.mark.asyncio
async def test_qna_both_exhausted_is_500_and_drops_empty_session(ask):
    response, models, _ = await ask(
        pass1=[_429(), _429(), _429()],
        final=[_503(), _503(), _503()],
    )

    assert response.status_code == 500, response.text
    assert models.calls == {"pass1": 3, "final": 3}
    assert await _rows(ChatMessage) == []
    assert await _rows(ChatSession) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, status",
    zip(NOT_RETRIED, [504, 500, 500]),
    ids=["504", "400", "403"],
)
async def test_qna_final_non_transient_error_is_not_retried(ask, error, status):
    response, models, _ = await ask(final=[error()])

    assert response.status_code == status, response.text
    assert models.calls == {"pass1": 1, "final": 1}
    assert await _rows(ChatSession) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("error", NOT_RETRIED)
async def test_qna_pass1_non_transient_error_falls_back_once(ask, error):
    response, models, _ = await ask(pass1=[error()])

    assert response.status_code == 200, response.text
    assert models.calls == {"pass1": 1, "final": 1}


@pytest.mark.asyncio
async def test_qna_save_failure_does_not_call_model_again(ask):
    with patch(
        "app.services.qna_service.QnAService._save_messages",
        AsyncMock(side_effect=RuntimeError("db down")),
    ):
        response, models, _ = await ask()

    assert response.status_code == 500, response.text
    assert models.calls == {"pass1": 1, "final": 1}
    assert await _rows(ChatSession) == []


# --- 평가: 기준 검색(search_in_store) + 최종 평가 ----------------------------


def _eval_stage(contents, config):
    return "search" if config.tools else "eval"


def _eval_service(**errors):
    models = FakeModels(_eval_stage, errors)
    client = SimpleNamespace(models=models, file_search_stores=Mock())
    client.file_search_stores.list = Mock(
        return_value=[SimpleNamespace(display_name="rubric", name="fs/r")]
    )
    file_search = FileSearchService.__new__(FileSearchService)
    file_search.client = client
    file_search._extract_citations = Mock(return_value=[{"title": "기준"}])
    criteria = CriteriaVectorService.__new__(CriteriaVectorService)
    criteria.file_search_service = file_search
    criteria.store_name = "rubric"

    service = EvaluationService.__new__(EvaluationService)
    service.client = client
    service.eval_model_name = "m"
    service.criteria_vector = criteria
    service.prompt_loader = Mock(get_prompt=Mock(return_value="system"))
    service.prompt_builder = Mock()
    service.prompt_builder.build_evaluation_prompt = Mock(return_value="P")
    service.prompt_builder.parse_evaluation_response = Mock(
        return_value={"feedback": "좋음"}
    )
    service._generate_markdown_report = Mock(return_value="# 보고서")
    service.analysis_storage = Mock()
    service.analysis_storage.save_analysis = Mock(
        return_value={"file_path": "p.md", "filename": "p.md"}
    )
    return service, models


async def _evaluate(service):
    test_app = FastAPI()
    test_app.include_router(evaluations.router)
    test_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, username="u"
    )
    with (
        patch.object(evaluations, "EvaluationService", return_value=service),
        patch.object(
            CriteriaVectorService,
            "active_stable_id_filter",
            AsyncMock(return_value='stable_id="A"'),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/api/evaluations", json={"lessonplan_filename": "plan.pdf"}
            )


@pytest.mark.asyncio
async def test_evaluation_first_responses_call_each_stage_once():
    service, models = _eval_service()

    response = await _evaluate(service)

    assert response.status_code == 201, response.text
    assert models.calls == {"search": 1, "eval": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["search", "eval"])
@pytest.mark.parametrize("error", TRANSIENT)
async def test_evaluation_transient_error_once_is_retried(stage, error):
    service, models = _eval_service(**{stage: [error()]})

    response = await _evaluate(service)

    assert response.status_code == 201, response.text
    other = "eval" if stage == "search" else "search"
    assert models.calls == {stage: 2, other: 1}
    service.criteria_vector.file_search_service.client.file_search_stores.list.assert_called_once()
    service.analysis_storage.save_analysis.assert_called_once()


@pytest.mark.asyncio
async def test_evaluation_search_and_eval_both_retried_saves_once():
    service, models = _eval_service(search=[_503()], eval=[_503()])

    response = await _evaluate(service)

    assert response.status_code == 201, response.text
    assert models.calls == {"search": 2, "eval": 2}
    service.analysis_storage.save_analysis.assert_called_once()


@pytest.mark.asyncio
async def test_evaluation_exhausted_is_500_and_saves_nothing():
    service, models = _eval_service(eval=[_503(), _503(), _503()])

    response = await _evaluate(service)

    assert response.status_code == 500, response.text
    assert models.calls == {"search": 1, "eval": 3}
    service.analysis_storage.save_analysis.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["search", "eval"])
@pytest.mark.parametrize("error", NOT_RETRIED)
async def test_evaluation_non_transient_error_is_not_retried(stage, error):
    service, models = _eval_service(**{stage: [error()]})

    response = await _evaluate(service)

    assert response.status_code == 500, response.text
    assert models.calls[stage] == 1
    service.analysis_storage.save_analysis.assert_not_called()


@pytest.mark.asyncio
async def test_evaluation_parse_or_save_failure_does_not_call_model_again():
    service, models = _eval_service()
    service.prompt_builder.parse_evaluation_response.side_effect = RuntimeError
    assert (await _evaluate(service)).status_code == 500
    assert models.calls == {"search": 1, "eval": 1}

    service, models = _eval_service()
    service.analysis_storage.save_analysis.side_effect = OSError("disk")
    assert (await _evaluate(service)).status_code == 500
    assert models.calls == {"search": 1, "eval": 1}
