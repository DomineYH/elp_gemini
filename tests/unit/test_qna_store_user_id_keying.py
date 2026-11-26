"""Tests verifying QnA File Search store lookups use user_id (issue #91 §0).

The QnA service must resolve stores as ``user-{user_id}-store``, not
``user-{username}-store``, so grounding matches the upload path.

These tests exercise the real ``ask_question`` code path to ensure the
store-lookup call receives the int ``user_id``, not the string ``username``.
"""

from collections import Counter
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db import Base, get_db
from app.dependencies import get_current_user
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.users import User
from app.routers import qna


def _mock_db():
    """Build a mock AsyncSession returning a valid session and empty history."""
    db = AsyncMock()
    mock_session = Mock()
    session_result = Mock()
    session_result.scalar_one_or_none.return_value = mock_session
    history_result = Mock()
    history_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(side_effect=[session_result, history_result])
    return db


def _make_service(db):
    """Create a QnAService with mocked Gemini client and prompt."""
    with patch("app.services.qna_service.genai.Client"):
        from app.services.qna_service import QnAService

        svc = QnAService(db=db)
    svc.prompt_loader.get_prompt = Mock(return_value="QnA system prompt")
    mock_resp = Mock()
    mock_resp.text = "answer"
    mock_resp.candidates = []
    svc.client.models.generate_content = Mock(return_value=mock_resp)
    return svc


# Patches for modules imported inside ask_question's body.
# These are scoped to the source modules so the in-function
# ``from X import Y`` picks up the mock.
_COMMON_PATCHES = [
    # criteria_context_service — make it return no context, no notice
    "app.services.criteria_context_service.CriteriaContextService",
    "app.services.criteria_context_service.build_criteria_context_or_notice",
    "app.repositories.app_state_repository.AppStateRepository",
    # question_analyzer
    "app.services.question_analyzer.QuestionAnalyzer",
]


class TestQnAStoreUserIdKeying:
    """Verify QnA passes user_id (int) to store lookups via ask_question."""

    @pytest.mark.asyncio
    async def test_general_question_uses_int_user_id_for_store(self):
        """
        Full ask_question path for a general question:
        ``get_user_store_id`` must receive ``user_key=42`` (int),
        NOT ``user_key="testuser"`` (str).
        """
        with patch.object(settings, "GOOGLE_API_KEY", "test-key"):
            db = _mock_db()
            svc = _make_service(db)

            # Spy on the store lookup
            svc.file_search_service.get_user_store_id = Mock(
                return_value="fileSearchStores/user42"
            )

            with (
                patch(_COMMON_PATCHES[0], Mock()),
                patch(_COMMON_PATCHES[1], AsyncMock(return_value=(None, None))),
                patch(_COMMON_PATCHES[2], Mock()),
                patch(_COMMON_PATCHES[3]) as MockQA,  # noqa: N806
            ):
                MockQA.return_value.analyze_question.return_value = {
                    "question_type": "general",
                    "metadata_filter": None,
                }

                result = await svc.ask_question(
                    session_id=1,
                    question="What is in my document?",
                    user_id=42,
                    username="testuser",
                )

            # THE critical assertion
            svc.file_search_service.get_user_store_id.assert_called_once()
            call_kwargs = svc.file_search_service.get_user_store_id.call_args
            assert call_kwargs.kwargs["user_key"] == 42
            assert isinstance(call_kwargs.kwargs["user_key"], int)
            # Sanity
            assert result["answer"] == "answer"

    @pytest.mark.asyncio
    async def test_eval_question_uses_int_user_id_for_store(self):
        """
        Full ask_question path for an evaluation question:
        ``get_dual_store_ids`` must receive ``user_key=42`` (int),
        NOT ``user_key="testuser"`` (str).
        """
        with patch.object(settings, "GOOGLE_API_KEY", "test-key"):
            db = _mock_db()
            svc = _make_service(db)

            # Spy on the store lookup
            svc.file_search_service.get_dual_store_ids = Mock(
                return_value=[
                    "fileSearchStores/user42",
                    "fileSearchStores/rubric",
                ]
            )

            with (
                patch(_COMMON_PATCHES[0], Mock()),
                patch(_COMMON_PATCHES[1], AsyncMock(return_value=(None, None))),
                patch(_COMMON_PATCHES[2], Mock()),
                patch(_COMMON_PATCHES[3]) as MockQA,  # noqa: N806
                patch(
                    "app.services.criteria_vector_service"
                    ".CriteriaVectorService.active_stable_id_filter",
                    new=AsyncMock(return_value="some_filter"),
                ),
            ):
                MockQA.return_value.analyze_question.return_value = {
                    "question_type": "evaluation",
                    "metadata_filter": None,
                }

                result = await svc.ask_question(
                    session_id=1,
                    question="Evaluate my lesson plan",
                    user_id=42,
                    username="testuser",
                )

            # THE critical assertion
            svc.file_search_service.get_dual_store_ids.assert_called_once()
            call_kwargs = svc.file_search_service.get_dual_store_ids.call_args
            assert call_kwargs.kwargs["user_key"] == 42
            assert isinstance(call_kwargs.kwargs["user_key"], int)
            # Sanity
            assert result["answer"] == "answer"

    def test_store_name_format_is_user_id_based(self):
        """
        The store name from user_id=42 must be 'user-42-store',
        matching the upload path convention.
        """
        from app.services.file_search_service import _sanitize_display_name

        assert _sanitize_display_name("user-42-store") == "user-42-store"

    def test_store_name_differs_from_username_based(self):
        """
        user-{id}-store != user-{username}-store for the same user,
        proving the re-keying actually changes the store target.
        """
        from app.services.file_search_service import _sanitize_display_name

        id_store = _sanitize_display_name("user-42-store")
        username_store = _sanitize_display_name("user-testuser-store")
        assert id_store != username_store


# --- #468 B: 색인된 최신 업로드가 없으면 QnA 를 거부한다 ---------------------

INDEX_MISSING_DETAIL = (
    "지도안 검색 색인이 없습니다. 지도안을 다시 업로드한 뒤 질문해 주세요."
)


class FakeGenai:
    """genai.Client 대역: 남은 user-{id}-store(문서 1개)와 호출 횟수 (#468)."""

    def __init__(self, user_id, answer="답변"):
        from app.services.lessonplan_analysis_service import (
            _LESSONPLAN_RETRIEVE_QUERY,
        )

        self.calls = Counter()
        self.configs = []
        self.user_store = f"fileSearchStores/u{user_id}"
        stores = [
            SimpleNamespace(
                name=self.user_store, display_name=f"user-{user_id}-store"
            ),
            SimpleNamespace(
                name="fileSearchStores/rubric", display_name="rubric-store"
            ),
        ]
        chunk = SimpleNamespace(
            retrieved_context=SimpleNamespace(
                title="plan.pdf", text="원문", uri=None
            )
        )
        pass1 = SimpleNamespace(
            text="지도안 원문",
            candidates=[
                SimpleNamespace(
                    grounding_metadata=SimpleNamespace(
                        grounding_chunks=[chunk]
                    ),
                    finish_reason=None,
                )
            ],
        )

        def count(name, value):
            def call(*args, **kwargs):
                self.calls[name] += 1
                return value(**kwargs) if callable(value) else value

            return call

        def generate(*, model, contents, config):
            self.configs.append(config)
            if contents == _LESSONPLAN_RETRIEVE_QUERY:
                return pass1
            return SimpleNamespace(text=answer, candidates=[])

        self.models = SimpleNamespace(
            generate_content=count("generate", generate)
        )
        self.file_search_stores = SimpleNamespace(
            list=count("stores.list", stores),
            create=count(
                "stores.create",
                SimpleNamespace(
                    name="fileSearchStores/new", display_name="new"
                ),
            ),
            documents=SimpleNamespace(
                list=count(
                    "documents.list", [SimpleNamespace(name="documents/old")]
                )
            ),
        )


@pytest_asyncio.fixture
async def qna_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/qna.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        users = [
            User(username=name, nickname=name, hashed_password="x")
            for name in ("newcomer", "other")
        ]
        db.add_all(users)
        await db.commit()
    yield factory, users[0], users[1]
    await engine.dispose()


@pytest_asyncio.fixture
async def qna_post(qna_db, monkeypatch):
    """가짜 SDK 로 실제 QnA 라우트·서비스를 부른다. (응답, fake)."""
    from app.services.file_search_service import FileSearchService

    factory, user, _ = qna_db
    test_app = FastAPI()
    test_app.include_router(qna.router)

    async def override_get_db():
        async with factory() as db:
            yield db

    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_current_user] = lambda: user

    async def _post(path, question="지도안의 학습 목표는?"):
        fake = FakeGenai(user.id)
        monkeypatch.setattr(FileSearchService, "_client", fake)
        with (
            patch("app.services.qna_service.genai.Client", return_value=fake),
            patch(
                "app.services.prompt_loader_service.PromptLoaderService.get_prompt",
                return_value="QnA system prompt",
            ),
            patch(
                "app.services.criteria_context_service."
                "build_criteria_context_or_notice",
                AsyncMock(return_value=(None, None)),
            ),
            patch(
                "app.services.criteria_vector_service"
                ".CriteriaVectorService.active_stable_id_filter",
                new=AsyncMock(return_value='stable_id="A"'),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=test_app),
                base_url="http://testserver",
            ) as client:
                response = await client.post(path, json={"question": question})
        return response, fake

    return _post


async def _qna_rows(factory, model):
    async with factory() as db:
        return (
            (await db.execute(select(model).order_by(model.id))).scalars().all()
        )


def _assert_rejected(response, fake):
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": INDEX_MISSING_DETAIL}
    assert fake.calls == {}


async def _seed_owned_session(factory, user):
    async with factory() as db:
        chat = ChatSession(user_id=user.id, title="old", user_type="미지정")
        db.add(chat)
        await db.flush()
        db.add_all(
            [
                ChatMessage(
                    session_id=chat.id, role=MessageRole.USER, content="q0"
                ),
                ChatMessage(
                    session_id=chat.id, role=MessageRole.ASSISTANT, content="a0"
                ),
            ]
        )
        await db.commit()
        return chat.id


async def _snapshot(factory):
    sessions = await _qna_rows(factory, ChatSession)
    messages = await _qna_rows(factory, ChatMessage)
    return [s.id for s in sessions], [
        (m.session_id, m.content) for m in messages
    ]


@pytest.mark.asyncio
async def test_document_ask_rejects_missing_upload(qna_db, qna_post):
    factory, _, _ = qna_db

    response, fake = await qna_post("/api/qna/no-such-document")

    _assert_rejected(response, fake)
    assert await _snapshot(factory) == ([], [])


@pytest.mark.asyncio
async def test_owned_session_ask_rejects_missing_upload(qna_db, qna_post):
    factory, user, _ = qna_db
    sid = await _seed_owned_session(factory, user)
    before = await _snapshot(factory)

    response, fake = await qna_post(f"/api/qna/sessions/{sid}/ask")

    _assert_rejected(response, fake)
    assert await _snapshot(factory) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("document_id", [None, ""], ids=["None", "빈 문자열"])
@pytest.mark.parametrize("route", ["document", "session"])
async def test_qna_rejects_latest_unindexed_upload(
    qna_db, qna_post, document_id, route
):
    factory, user, other = qna_db
    same_time = datetime(2026, 11, 26, 9, 0, 0)
    async with factory() as db:
        db.add_all(
            [
                # 과거 색인 행과 다른 사용자의 유효 행은 판정에 쓰지 않는다
                LessonPlanUpload(
                    user_id=user.id,
                    filename="old.pdf",
                    original_filename="old.pdf",
                    fs_document_id="documents/old",
                    created_at=datetime(2026, 11, 1),
                ),
                LessonPlanUpload(
                    user_id=user.id,
                    filename="tie_indexed.pdf",
                    original_filename="tie_indexed.pdf",
                    fs_document_id="documents/tie",
                    created_at=same_time,
                ),
                LessonPlanUpload(
                    user_id=user.id,
                    filename="latest.pdf",
                    original_filename="latest.pdf",
                    fs_document_id=document_id,
                    created_at=same_time,
                ),
                LessonPlanUpload(
                    user_id=other.id,
                    filename="other.pdf",
                    original_filename="other.pdf",
                    fs_document_id="documents/other",
                    created_at=datetime(2026, 11, 27),
                ),
            ]
        )
        await db.commit()
    path = "/api/qna/documents/x"
    if route == "session":
        path = (
            f"/api/qna/sessions/{await _seed_owned_session(factory, user)}/ask"
        )
    before = await _snapshot(factory)
    uploads_before = len(await _qna_rows(factory, LessonPlanUpload))

    response, fake = await qna_post(path)

    _assert_rejected(response, fake)
    assert await _snapshot(factory) == before
    assert len(await _qna_rows(factory, LessonPlanUpload)) == uploads_before


async def _seed_indexed_upload(factory, user, original="plan.pdf"):
    async with factory() as db:
        upload = LessonPlanUpload(
            user_id=user.id,
            filename="newcomer_plan.pdf",
            original_filename=original,
            fs_document_id="documents/new",
        )
        db.add(upload)
        await db.commit()
        return upload.id


def _store_names(config):
    return [tool.file_search.file_search_store_names for tool in config.tools]


@pytest.mark.asyncio
async def test_indexed_upload_keeps_qna_search(qna_db, qna_post):
    factory, user, _ = qna_db
    upload_id = await _seed_indexed_upload(factory, user)

    # 일반 질문: 자기 스토어 도구 하나 (다른 문서 키로도 같은 스토어)
    response, fake = await qna_post("/api/qna/someone-elses-document")
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "답변"
    assert fake.calls["generate"] == 1
    assert fake.calls["stores.create"] == 0
    assert [_store_names(c) for c in fake.configs] == [[[fake.user_store]]]
    (chat,) = await _qna_rows(factory, ChatSession)
    assert (chat.upload_id, chat.title) == (upload_id, "plan.pdf")
    assert chat.document_id == "someone-elses-document"

    # 평가 질문: 1패스 사용자 스토어, 2패스 활성 필터 rubric
    response, fake = await qna_post(
        f"/api/qna/sessions/{chat.id}/ask", question="이 수업을 평가해줘"
    )
    assert response.status_code == 200, response.text
    pass1, final = fake.configs
    assert _store_names(pass1) == [[fake.user_store]]
    assert [
        (t.file_search.file_search_store_names, t.file_search.metadata_filter)
        for t in final.tools
    ] == [(["fileSearchStores/rubric"], 'stable_id="A"')]
    assert len(await _qna_rows(factory, ChatMessage)) == 4
