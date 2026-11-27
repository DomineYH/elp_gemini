"""Active criteria metadata filters for rubric File Search call sites."""

import asyncio
import base64
import contextvars
import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from google.genai import errors as genai_errors
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.repositories.app_state_repository import (
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
    AppStateRepository,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.alias_map_codec import encode_alias_map_payload
from app.services.file_search_service import _sanitize_display_name

# #439: 저장 전 검사를 통과하는 1~5절 제목 본문
VALID_SECTIONS = "".join(f"## {n}. 절\n\n본문\n\n" for n in range(1, 6))


def _file_search_for_store(config, store_name: str):
    for tool in config.tools:
        file_search = tool.file_search
        if file_search.file_search_store_names == [store_name]:
            return file_search
    return None


@pytest.mark.asyncio
async def test_active_stable_id_filter_ignores_legacy_surrogate_active_entries():
    from app.services.criteria_vector_service import CriteriaVectorService

    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-15T00:00:00Z",
        entries={
            "01HREAL": AliasMapEntry(
                alias=None,
                status="active",
                activated_at="2026-05-15T00:00:00Z",
            ),
            "legacy_0123456789abcdef": AliasMapEntry(
                alias=None,
                status="active",
                activated_at="2026-05-16T00:00:00Z",
            ),
        },
    )

    with patch(
        "app.services.criteria_alias_map_service.CriteriaAliasMapService"
    ) as alias_cls:
        alias_cls.return_value.fetch = AsyncMock(
            return_value=("docs/alias-map", alias_map)
        )

        metadata_filter = await CriteriaVectorService.active_stable_id_filter(
            client=MagicMock(),
            store_display_name="rubric-store",
        )

    assert metadata_filter == 'stable_id="01HREAL"'


@pytest.mark.asyncio
async def test_active_stable_id_filter_returns_none_when_only_legacy_is_active():
    from app.services.criteria_vector_service import CriteriaVectorService

    alias_map = AliasMap(
        schema_version=1,
        updated_at="2026-05-15T00:00:00Z",
        entries={
            "legacy_0123456789abcdef": AliasMapEntry(
                alias=None,
                status="active",
                activated_at="2026-05-16T00:00:00Z",
            ),
        },
    )

    with patch(
        "app.services.criteria_alias_map_service.CriteriaAliasMapService"
    ) as alias_cls:
        alias_cls.return_value.fetch = AsyncMock(
            return_value=("docs/alias-map", alias_map)
        )

        metadata_filter = await CriteriaVectorService.active_stable_id_filter(
            client=MagicMock(),
            store_display_name="rubric-store",
        )

    assert metadata_filter is None


def test_lessonplan_two_pass_retrieves_user_then_filters_only_rubric_store():
    """#118: 긴 평가 프롬프트는 나쁜 File Search retrieval 쿼리이므로 두 패스로
    분리한다.

    - 1패스: 사용자 스토어만 대상으로 지도안 원문을 검색(내용 지향 질의).
    - 2패스: 1패스에서 받은 원문을 평가 프롬프트에 주입하고, rubric 스토어
      (활성 stable_id 필터 적용)만으로 평가 보고서를 생성한다.

    이로써 평가 시 사용자 지도안이 실제로 grounding 되어 '현재 지도안(A)'
    인용이 빈 값('해당 서술 없음')으로 떨어지지 않는다.
    """
    from app.services.lessonplan_analysis_service import (
        _call_gemini_with_file_search,
    )

    client = MagicMock()
    pass1 = SimpleNamespace(
        text="제목: 미래 인구 예측 / 학습목표: ...",
        # #449: 검색 근거가 있어야 지도안 원문으로 본다
        candidates=[
            SimpleNamespace(
                grounding_metadata=SimpleNamespace(grounding_chunks=[object()])
            )
        ],
    )
    pass2 = SimpleNamespace(text="report", candidates=[])
    client.models.generate_content.side_effect = [pass1, pass2]

    result = _call_gemini_with_file_search(
        client,
        "gemini-eval",
        "EVAL_PROMPT_BODY",
        "fileSearchStores/rubric",
        "fileSearchStores/user",
        'stable_id="01HACTIVE"',
    )

    assert result is pass2
    assert client.models.generate_content.call_count == 2

    # 1패스: 사용자 스토어만, rubric 없음
    c1 = client.models.generate_content.call_args_list[0].kwargs["config"]
    assert _file_search_for_store(c1, "fileSearchStores/user") is not None
    assert _file_search_for_store(c1, "fileSearchStores/rubric") is None

    # 2패스: rubric 스토어만(활성 필터 적용), 사용자 스토어 없음
    c2 = client.models.generate_content.call_args_list[1].kwargs["config"]
    rubric_search = _file_search_for_store(c2, "fileSearchStores/rubric")
    assert rubric_search is not None
    assert rubric_search.metadata_filter == 'stable_id="01HACTIVE"'
    assert _file_search_for_store(c2, "fileSearchStores/user") is None

    # 1패스에서 검색한 지도안 원문이 2패스 평가 프롬프트에 주입됨
    pass2_contents = client.models.generate_content.call_args_list[1].kwargs[
        "contents"
    ]
    assert "EVAL_PROMPT_BODY" in pass2_contents
    assert "미래 인구 예측" in pass2_contents


@pytest.mark.asyncio
async def test_lessonplan_analysis_skips_gemini_when_no_active_criteria():
    from app.services.lessonplan_analysis_service import (
        LessonPlanAnalysisService,
    )

    db = AsyncMock()
    client = MagicMock()

    with (
        patch(
            "app.services.lessonplan_analysis_service.genai.Client",
            return_value=client,
        ),
        patch("app.services.lessonplan_analysis_service.FileSearchService"),
    ):
        service = LessonPlanAnalysisService(db)

    service._find_existing_report_for_latest_upload = AsyncMock(
        return_value=(
            SimpleNamespace(
                id=11,
                filename="lesson.pdf",
                original_filename="lesson.pdf",
                fs_document_id="documents/11",
                fs_store_id="fileSearchStores/user",
            ),
            None,
        )
    )
    service._get_store_ids = AsyncMock(
        return_value=["fileSearchStores/user", "fileSearchStores/rubric"]
    )
    service.prompt_loader.get_prompt = MagicMock(return_value="{model_name}")
    service.report_storage.save_report = MagicMock(
        return_value={"filename": "report.md", "file_path": "/tmp/report.md"}
    )

    with (
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value=None),
            create=True,
        ),
        patch(
            "app.services.lessonplan_analysis_service._call_gemini_with_file_search",
            return_value=SimpleNamespace(text="report", candidates=[]),
        ) as gemini_call,
    ):
        result = await service.analyze_lesson_plan(
            session_id=1,
            user_id=7,
        )

    assert result["success"] is False
    assert result["error_code"] == "NO_ACTIVE_CRITERIA"
    gemini_call.assert_not_called()


@pytest.mark.asyncio
async def test_lessonplan_analysis_stops_when_active_filter_fails():
    from app.services.lessonplan_analysis_service import (
        LessonPlanAnalysisService,
    )

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    client = MagicMock()

    with (
        patch(
            "app.services.lessonplan_analysis_service.genai.Client",
            return_value=client,
        ),
        patch("app.services.lessonplan_analysis_service.FileSearchService"),
        patch(
            "app.services.lessonplan_analysis_service.AppStateRepository",
            create=True,
        ) as state_cls,
    ):
        state = state_cls.return_value
        state.set = AsyncMock()
        service = LessonPlanAnalysisService(db)

        service._find_existing_report_for_latest_upload = AsyncMock(
            return_value=(
                SimpleNamespace(
                    id=11,
                    filename="lesson.pdf",
                    original_filename="lesson.pdf",
                    fs_document_id="documents/11",
                    fs_store_id="fileSearchStores/user",
                ),
                None,
            )
        )
        service._get_store_ids = AsyncMock(
            return_value=["fileSearchStores/user", "fileSearchStores/rubric"]
        )
        # alias fetch도 to_thread를 쓰므로 Gemini 호출 인자 검사를 위해 막는다.
        service._collect_active_criteria_display_names = AsyncMock(
            return_value=[]
        )
        service.prompt_loader.get_prompt = MagicMock(
            return_value="{model_name}"
        )
        service.report_storage.save_report = MagicMock(
            return_value={
                "filename": "report.md",
                "file_path": "/tmp/report.md",
            }
        )

        with (
            patch(
                "app.services.criteria_vector_service."
                "CriteriaVectorService.active_stable_id_filter",
                new=AsyncMock(side_effect=RuntimeError("alias map corrupt")),
                create=True,
            ),
            patch(
                "app.services.lessonplan_analysis_service.asyncio.to_thread",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        text=VALID_SECTIONS, candidates=[]
                    )
                ),
            ) as gemini_call,
        ):
            result = await service.analyze_lesson_plan(
                session_id=1,
                user_id=7,
            )

    assert result == {
        "success": False,
        "error_code": "CRITERIA_SYNC_REQUIRED",
        "error": "평가기준 동기화가 필요합니다. 관리자에게 문의하세요.",
    }
    gemini_call.assert_not_awaited()
    service.report_storage.save_report.assert_not_called()
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")
    state.set.assert_any_await(KEY_SYNC_ERROR, "alias map corrupt")
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_qna_evaluation_filters_rubric_store_by_active_stable_id():
    from app.services.qna_service import QnAService

    db = AsyncMock()
    # 색인된 최신 업로드가 있다 (#468)
    db.execute.return_value.scalar_one_or_none = MagicMock(
        return_value=MagicMock(
            fs_document_id="documents/d", fs_store_id="fileSearchStores/user"
        )
    )
    client = MagicMock()
    response = MagicMock()
    response.text = "answer"
    response.candidates = []
    client.models.generate_content.return_value = response

    with (
        patch(
            "app.services.qna_service.genai.Client",
            return_value=client,
        ),
        patch("app.services.qna_service.FileSearchService") as file_search_cls,
        patch(
            "app.services.criteria_context_service.build_criteria_context_or_notice",
            new=AsyncMock(return_value=(None, None)),
        ),
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value='stable_id="01HACTIVE"'),
            create=True,
        ),
    ):
        file_search = file_search_cls.return_value
        file_search.get_rubric_store_id = MagicMock(
            return_value="fileSearchStores/rubric"
        )

        service = QnAService(db)
        service._get_session = AsyncMock(
            return_value=SimpleNamespace(id=1, user_id=7)
        )
        service.prompt_loader.get_prompt = MagicMock(return_value="system")
        service.get_conversation_history = AsyncMock(return_value=[])
        service._save_messages = AsyncMock()

        await service.ask_question(
            session_id=1,
            question="이 수업을 평가해줘",
            user_id=7,
            username="teacher",
        )

    # 2-패스(#199): 1패스는 user store만(필터 없음), 2패스는 rubric만
    pass1, pass2 = client.models.generate_content.call_args_list
    user_search = _file_search_for_store(
        pass1.kwargs["config"], "fileSearchStores/user"
    )
    rubric_search = _file_search_for_store(
        pass2.kwargs["config"], "fileSearchStores/rubric"
    )

    assert rubric_search is not None
    assert rubric_search.metadata_filter == 'stable_id="01HACTIVE"'
    assert user_search is not None
    assert getattr(user_search, "metadata_filter", None) is None


@pytest.mark.asyncio
async def test_qna_evaluation_skips_rubric_store_when_no_active_criteria():
    from app.services.qna_service import QnAService

    db = AsyncMock()
    # 색인된 최신 업로드가 있다 (#468)
    db.execute.return_value.scalar_one_or_none = MagicMock(
        return_value=MagicMock(
            fs_document_id="documents/d", fs_store_id="fileSearchStores/user"
        )
    )
    client = MagicMock()
    response = MagicMock()
    response.text = "answer"
    response.candidates = []
    client.models.generate_content.return_value = response

    with (
        patch(
            "app.services.qna_service.genai.Client",
            return_value=client,
        ),
        patch("app.services.qna_service.FileSearchService") as file_search_cls,
        patch(
            "app.services.criteria_context_service.build_criteria_context_or_notice",
            new=AsyncMock(return_value=(None, None)),
        ),
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(return_value=None),
            create=True,
        ),
    ):
        file_search = file_search_cls.return_value
        file_search.get_rubric_store_id = MagicMock(
            return_value="fileSearchStores/rubric"
        )

        service = QnAService(db)
        service._get_session = AsyncMock(
            return_value=SimpleNamespace(id=1, user_id=7)
        )
        service.prompt_loader.get_prompt = MagicMock(return_value="system")
        service.get_conversation_history = AsyncMock(return_value=[])
        service._save_messages = AsyncMock()

        await service.ask_question(
            session_id=1,
            question="이 수업을 평가해줘",
            user_id=7,
            username="teacher",
        )

    config = client.models.generate_content.call_args.kwargs["config"]
    all_store_names = [
        name
        for tool in config.tools
        for name in tool.file_search.file_search_store_names
    ]

    assert all_store_names == ["fileSearchStores/user"]
    sent_contents = client.models.generate_content.call_args.kwargs["contents"]
    assert "활성 평가기준이 없습니다" in sent_contents


@pytest.mark.asyncio
async def test_qna_evaluation_continues_user_store_when_active_filter_fails():
    from app.services.qna_service import QnAService

    db = AsyncMock()
    # 색인된 최신 업로드가 있다 (#468)
    db.execute.return_value.scalar_one_or_none = MagicMock(
        return_value=MagicMock(
            fs_document_id="documents/d", fs_store_id="fileSearchStores/user"
        )
    )
    client = MagicMock()
    response = MagicMock()
    response.text = "answer"
    response.candidates = []
    client.models.generate_content.return_value = response

    with (
        patch(
            "app.services.qna_service.genai.Client",
            return_value=client,
        ),
        patch("app.services.qna_service.FileSearchService") as file_search_cls,
        patch(
            "app.services.criteria_context_service.build_criteria_context_or_notice",
            new=AsyncMock(return_value=(None, None)),
        ),
        patch(
            "app.repositories.app_state_repository.AppStateRepository"
        ) as state_cls,
        patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(side_effect=RuntimeError("alias map corrupt")),
            create=True,
        ),
    ):
        state = state_cls.return_value
        state.set = AsyncMock()
        file_search = file_search_cls.return_value
        file_search.get_rubric_store_id = MagicMock(
            return_value="fileSearchStores/rubric"
        )

        service = QnAService(db)
        service._get_session = AsyncMock(
            return_value=SimpleNamespace(id=1, user_id=7)
        )
        service.prompt_loader.get_prompt = MagicMock(return_value="system")
        service.get_conversation_history = AsyncMock(return_value=[])
        service._save_messages = AsyncMock()

        result = await service.ask_question(
            session_id=1,
            question="이 수업을 평가해줘",
            user_id=7,
            username="teacher",
        )

    assert result["criteria_notice"]
    assert "평가기준" in result["criteria_notice"]
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")

    config = client.models.generate_content.call_args.kwargs["config"]
    all_store_names = [
        name
        for tool in config.tools
        for name in tool.file_search.file_search_store_names
    ]
    assert all_store_names == ["fileSearchStores/user"]


# ── #465: 활성 기준 조회의 일시 오류는 이번 요청만 실패시키고 전역 상태를 바꾸지 않는다 ──
# 진짜: 라우터, 두 서비스, alias fetch, AppStateRepository, 임시 SQLite(커밋·롤백).
# 가짜: 로그인 사용자, genai 클라이언트, 분석 생성 호출, 보고서 파일 저장, QnA 대화 저장.

_SCOPE = contextvars.ContextVar("scope465", default=())
_ALIAS_UPDATED_AT = "2026-11-25T07:09:39Z"
_ALIAS_MAP = {
    "schema_version": 1,
    "updated_at": _ALIAS_UPDATED_AT,
    "entries": {
        "SIDA": {
            "alias": "기준 A",
            "status": "active",
            "activated_at": "2026-11-01T00:00:00Z",
        },
        "SIDB": {"alias": "기준 B", "status": "uploaded", "activated_at": None},
    },
}
_Q_EVAL, _Q_PLAIN = "이 수업을 평가해줘", "이 지도안의 학습 목표가 뭐야?"
_DELAYED = "AI 서비스 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요."


def _scoped(name, fn):
    async def wrapper(*args, **kwargs):
        token = _SCOPE.set(_SCOPE.get() + (name,))
        try:
            return await fn(*args, **kwargs)
        finally:
            _SCOPE.reset(token)

    return wrapper


def _timeout():
    return httpx.ReadTimeout("The read operation timed out")


def _protocol():
    return httpx.RemoteProtocolError("Server disconnected")


def _sdk(code):
    status = {
        503: "UNAVAILABLE",
        520: "UNKNOWN",
        429: "RESOURCE_EXHAUSTED",
        403: "DENIED",
    }
    error_cls = (
        genai_errors.ServerError if code >= 500 else genai_errors.ClientError
    )
    return lambda: error_cls(
        code,
        {
            "error": {
                "code": code,
                "message": "sensitive-marker",
                "status": status[code],
            }
        },
    )


class _FakeGenai:
    """genai.Client 대역. 활성 기준 조회(최상위 'active' 범위)의 GET 에만 실패를 건다."""

    def __init__(self, user_ids):
        self.user_ids = user_ids
        self.active_fail = None  # (kind 또는 None=둘 다, 실패 횟수, 예외 생성)
        self.active_failed = 0
        self.corrupt = self.no_alias = False
        self.calls, self.gens = [], []
        self.file_search_stores = SimpleNamespace(
            list=self._stores,
            get=lambda name=None, **kwargs: _store_ns("", name),
            upload_to_file_search_store=self._write,
            documents=SimpleNamespace(list=self._docs, delete=self._write),
        )
        self.models = SimpleNamespace(generate_content=self._generate)

    def _tick(self, kind, kwargs):
        scope = _SCOPE.get()
        self.calls.append((kind, scope, kwargs.get("config")))
        if self.active_fail and scope[:1] == ("active",):
            fail_kind, times, make = self.active_fail
            if fail_kind in (None, kind) and self.active_failed < times:
                self.active_failed += 1
                raise make()

    def active_calls(self, kind):
        return [
            c for c in self.calls if c[0] == kind and c[1][:1] == ("active",)
        ]

    def _stores(self, **kwargs):
        self._tick("stores", kwargs)
        return [
            _store_ns(settings.FS_RUBRIC_STORE_NAME, "fileSearchStores/rubric")
        ] + [
            _store_ns(
                _sanitize_display_name(f"user-{uid}-store"),
                f"fileSearchStores/user{uid}",
            )
            for uid in self.user_ids
        ]

    def _docs(self, parent=None, **kwargs):
        self._tick("docs", kwargs)
        if parent != "fileSearchStores/rubric":
            return []
        docs = [
            SimpleNamespace(
                name=f"{parent}/documents/{sid.lower()}",
                display_name=f"{sid}.pdf",
                custom_metadata=[
                    {"key": "type", "string_value": "criteria"},
                    {"key": "stable_id", "string_value": sid},
                    {
                        "key": "original_title_b64",
                        "string_value": base64.b64encode(
                            f"{sid}.pdf".encode()
                        ).decode(),
                    },
                ],
            )
            for sid in _ALIAS_MAP["entries"]
        ]
        if not self.no_alias:
            chunks = (
                ["!!!깨진 payload"]
                if self.corrupt
                else encode_alias_map_payload(_ALIAS_MAP)
            )
            docs.append(
                SimpleNamespace(
                    name=f"{parent}/documents/aliasmap",
                    display_name="alias-map",
                    custom_metadata=[
                        {"key": "type", "string_value": "alias_map"},
                        {
                            "key": "payload_b64",
                            "string_list_value": {"values": chunks},
                        },
                    ],
                )
            )
        return docs

    def _write(self, *args, **kwargs):
        raise AssertionError("쓰기 호출이 나오면 안 된다")

    def _generate(self, model=None, contents=None, config=None, **kwargs):
        tools = [
            t.file_search
            for t in (config.tools or [])
            if getattr(t, "file_search", None)
        ]
        self.gens.append(
            {
                "scope": _SCOPE.get(),
                "stores": [s for t in tools for s in t.file_search_store_names],
                "filters": [t.metadata_filter for t in tools],
            }
        )
        return SimpleNamespace(text="가짜 답변입니다.", candidates=[])

    def answer_gens(self):
        return [g for g in self.gens if g["scope"] == ()]


def _store_ns(display_name, name):
    return SimpleNamespace(display_name=display_name, name=name)


@pytest_asyncio.fixture
async def env465(tmp_path, monkeypatch):
    from app.db import create_tables, get_db
    from app.dependencies import get_current_user
    from app.main import app
    from app.models.lessonplan_uploads import LessonPlanUpload
    from app.models.users import User
    from app.services import lessonplan_analysis_service as lpa_mod
    from app.services import qna_service as qna_mod
    from app.services.criteria_vector_service import CriteriaVectorService
    from app.services.file_search_service import FileSearchService
    from app.services.lessonplan_analysis_service import (
        LessonPlanAnalysisService,
    )
    from app.services.qna_service import QnAService
    from app.services.report_storage_service import ReportStorageService

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/app.db")
    await create_tables(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    users = {}
    async with maker() as s:
        for name, admin in (("A", False), ("B", False), ("admin", True)):
            users[name] = User(
                username=f"user{name}",
                nickname=name,
                hashed_password="x",
                is_admin=admin,
            )
            s.add(users[name])
        await s.flush()
        for name in ("A", "B"):
            uid = users[name].id
            s.add(
                LessonPlanUpload(
                    user_id=uid,
                    filename=f"u{uid}.pdf",
                    original_filename="lessonplan_ko.pdf",
                    fs_document_id=f"fileSearchStores/user{uid}/documents/d",
                    fs_store_id=f"fileSearchStores/user{uid}",
                )
            )
        repo = AppStateRepository(db=s)
        await repo.set(KEY_SYNC_STATE, "ok")
        await s.commit()

    async def override_db():
        # app.db.get_db 와 같은 경계: 성공하면 응답 뒤 커밋, 예외면 롤백
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    current = {"user": users["A"]}
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: current["user"]

    fake = _FakeGenai([u.id for u in users.values()])
    slept, saved, analysis_gens = [], [], []
    monkeypatch.setattr(time, "sleep", slept.append)

    def fake_analysis_generate(client, model, prompt, rubric, user, filt):
        analysis_gens.append({"filter": filt, "scope": _SCOPE.get()})
        return SimpleNamespace(text=VALID_SECTIONS, candidates=[])

    def fake_save(self, **kwargs):
        saved.append(kwargs)
        return {
            "filename": f"r{len(saved)}.md",
            "timestamp": "20261126000000",
            "file_path": str(tmp_path / f"r{len(saved)}.md"),
        }

    marks = {"analysis": MagicMock(), "qna": MagicMock()}
    real_mark_analysis = lpa_mod._mark_criteria_filter_needs_resync
    real_mark_qna = qna_mod._mark_criteria_filter_needs_resync

    async def mark_analysis(*a):
        marks["analysis"](*a)
        return await real_mark_analysis(*a)

    async def mark_qna(*a):
        marks["qna"](*a)
        return await real_mark_qna(*a)

    session = SimpleNamespace(id=1, user_id=None)

    async def get_session(self, session_id, user_id=None, *a, **k):
        session.user_id = current["user"].id
        return session

    patches = [
        patch("google.genai.Client", return_value=fake),
        patch.object(FileSearchService, "_client", fake),
        patch.object(QnAService, "_get_session", get_session),
        patch.object(
            QnAService, "get_conversation_history", AsyncMock(return_value=[])
        ),
        patch.object(QnAService, "_save_messages", AsyncMock()),
        patch.object(
            lpa_mod, "_call_gemini_with_file_search", fake_analysis_generate
        ),
        patch.object(
            lpa_mod, "_mark_criteria_filter_needs_resync", mark_analysis
        ),
        patch.object(qna_mod, "_mark_criteria_filter_needs_resync", mark_qna),
        patch.object(ReportStorageService, "save_report", fake_save),
        patch.object(
            CriteriaVectorService,
            "search_criteria",
            _scoped("context", CriteriaVectorService.search_criteria),
        ),
        patch.object(
            CriteriaVectorService,
            "active_stable_id_filter",
            staticmethod(
                _scoped("active", CriteriaVectorService.active_stable_id_filter)
            ),
        ),
        patch.object(
            LessonPlanAnalysisService,
            "_collect_active_criteria_display_names",
            _scoped(
                "display",
                LessonPlanAnalysisService._collect_active_criteria_display_names,
            ),
        ),
    ]
    for p in patches:
        p.start()

    async def state():
        async with maker() as s:
            repo = AppStateRepository(db=s)
            return await repo.get(KEY_SYNC_STATE), await repo.get(
                KEY_SYNC_ERROR
            )

    async def report_rows():
        from app.models.analysis_reports import AnalysisReport

        async with maker() as s:
            return len((await s.execute(select(AnalysisReport))).all())

    async def set_ok():
        async with maker() as s:
            repo = AppStateRepository(db=s)
            await repo.set(KEY_SYNC_STATE, "ok")
            await repo.set(KEY_SYNC_ERROR, None)
            await s.commit()

    def as_user(name):
        current["user"] = users[name]

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield SimpleNamespace(
                client=client,
                fake=fake,
                slept=slept,
                saved=saved,
                analysis_gens=analysis_gens,
                marks=marks,
                state=state,
                report_rows=report_rows,
                set_ok=set_ok,
                as_user=as_user,
            )
    finally:
        for p in reversed(patches):
            p.stop()
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        await engine.dispose()


async def _analyze(env):
    res = await env.client.post(
        "/api/lessonplan/analyze", json={"session_id": 1}
    )
    status_res = await env.client.get("/api/lessonplan/analyze/status")
    return res, status_res.json()["in_progress"]


async def _ask(env, question=_Q_EVAL):
    return await env.client.post(
        "/api/qna/sessions/1/ask", json={"question": question}
    )


def _assert_lookup_timeouts(env):
    lookups = env.fake.active_calls("stores") + env.fake.active_calls("docs")
    assert lookups
    assert all(c[2] == {"http_options": {"timeout": 10_000}} for c in lookups)


@pytest.mark.asyncio
async def test_analysis_active_lookup_retry(env465):
    env = env465
    env.fake.active_fail = ("stores", 1, _timeout)

    res, in_progress = await _analyze(env)

    assert res.status_code == 200, res.text
    assert [g["filter"] for g in env.analysis_gens] == ['stable_id="SIDA"']
    assert len(env.fake.active_calls("stores")) == 2
    assert len(env.fake.active_calls("docs")) == 1
    _assert_lookup_timeouts(env)
    assert in_progress is False
    assert await env.state() == ("ok", None)
    env.marks["analysis"].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make, code, detail",
    [
        (_timeout, 503, _DELAYED),
        (_protocol, 503, _DELAYED),
        (_sdk(503), 503, "혼잡"),
        (_sdk(429), 429, "요청량"),
    ],
)
async def test_analysis_active_lookup_exhausted(env465, make, code, detail):
    env = env465
    env.fake.active_fail = ("stores", 99, make)

    res, in_progress = await _analyze(env)

    assert res.status_code == code, res.text
    assert res.headers["retry-after"] == "30"
    assert detail in res.json()["detail"]
    assert len(env.fake.active_calls("stores")) == 3
    assert (env.analysis_gens, env.saved, in_progress) == ([], [], False)
    assert await env.report_rows() == 0
    assert await env.state() == ("ok", None)
    env.marks["analysis"].assert_not_called()


@pytest.mark.asyncio
async def test_analysis_active_lookup_other_5xx(env465, caplog):
    env = env465
    body = {"error": {"code": 520, "message": "sensitive-marker"}}
    env.fake.active_fail = (
        "stores",
        99,
        lambda: genai_errors.ServerError(520, body),
    )

    res, in_progress = await _analyze(env)

    # SDK 오류 원문은 로그에 남지 않고 종류와 상태 코드만 남는다 (#484)
    assert "sensitive-marker" not in caplog.text
    assert "ServerError 520" in caplog.text
    assert res.status_code == 503, res.text
    assert res.headers["retry-after"] == "30"
    assert "혼잡" in res.json()["detail"]
    # 공유 재시도 집합(500/502/503/504)은 그대로라 520 은 한 번만 부른다
    assert len(env.fake.active_calls("stores")) == 1
    assert (env.analysis_gens, env.saved, in_progress) == ([], [], False)
    assert await env.report_rows() == 0
    assert await env.state() == ("ok", None)
    env.marks["analysis"].assert_not_called()


@pytest.mark.asyncio
async def test_evaluation_active_lookup_retry(env465):
    env = env465
    env.fake.active_fail = ("docs", 1, _protocol)

    res = await _ask(env)

    assert res.status_code == 200, res.text
    assert res.json()["criteria_notice"] is None
    # 2-패스(#199): 지도안 검색 뒤 rubric 스토어만 활성 필터로
    assert [(g["stores"], g["filters"]) for g in env.fake.answer_gens()] == [
        (["fileSearchStores/user1"], [None]),
        (["fileSearchStores/rubric"], ['stable_id="SIDA"']),
    ]
    assert len(env.fake.active_calls("docs")) == 2
    _assert_lookup_timeouts(env)
    assert await env.state() == ("ok", None)
    env.marks["qna"].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make, code, detail",
    [
        (
            _timeout,
            504,
            "AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
        ),
        (_protocol, 500, "질문 처리 중 오류가 발생했습니다."),
        (_sdk(503), 500, "질문 처리 중 오류가 발생했습니다."),
        (_sdk(429), 500, "질문 처리 중 오류가 발생했습니다."),
    ],
)
async def test_evaluation_active_lookup_exhausted(env465, make, code, detail):
    env = env465
    env.fake.active_fail = (None, 99, make)

    res = await _ask(env)

    assert res.status_code == code, res.text
    assert res.json()["detail"] == detail
    # 앞선 기준 컨텍스트 검색의 생성은 남고, 최종 답변 생성만 없다
    assert [g["scope"] for g in env.fake.gens] == [("context",)]
    assert len(env.fake.active_calls("stores")) == 3
    assert await env.state() == ("ok", None)
    env.marks["qna"].assert_not_called()


@pytest.mark.asyncio
async def test_evaluation_active_lookup_other_5xx(env465):
    env = env465
    env.fake.active_fail = (None, 99, _sdk(520))

    res = await _ask(env)

    assert res.status_code == 500, res.text
    assert res.json()["detail"] == "질문 처리 중 오류가 발생했습니다."
    assert [g["scope"] for g in env.fake.gens] == [("context",)]
    assert len(env.fake.active_calls("stores")) == 1
    assert await env.state() == ("ok", None)
    env.marks["qna"].assert_not_called()


@pytest.mark.asyncio
async def test_other_user_after_active_lookup_failure(env465):
    from app.services.criteria_alias_map_service import CriteriaAliasMapService

    env = env465
    env.fake.active_fail = (None, 99, _timeout)
    assert (await _ask(env)).status_code == 504

    env.fake.active_fail = None
    env.fake.gens.clear()
    env.as_user("B")
    res = await _ask(env, _Q_PLAIN)
    assert res.status_code == 200, res.text
    assert res.json()["criteria_notice"] is None
    assert [g["scope"] for g in env.fake.gens] == [("context",), ()]

    env.as_user("admin")
    with patch.object(
        CriteriaAliasMapService, "replace", AsyncMock(return_value="docs/new")
    ):
        res = await env.client.post("/api/admin/criteria/SIDB/activate")
    assert res.status_code == 200, res.text
    assert await env.state() == ("ok", None)


_PERSISTENT = [
    ("corrupt", "parse failed"),
    ("sdk403", "ClientError 403"),
    ("runtime", "boom"),
]


def _arm_persistent(env, cause):
    if cause == "corrupt":
        env.fake.corrupt = True
    else:
        make = _sdk(403) if cause == "sdk403" else lambda: RuntimeError("boom")
        env.fake.active_fail = ("stores", 99, make)


@pytest.mark.asyncio
@pytest.mark.parametrize("cause, stored", _PERSISTENT)
async def test_persistent_active_lookup_failure(env465, caplog, cause, stored):
    env = env465
    _arm_persistent(env, cause)

    res = await _ask(env)
    assert res.status_code == 200, res.text
    assert "평가기준" in res.json()["criteria_notice"]
    assert env.fake.answer_gens()[-1]["stores"] == ["fileSearchStores/user1"]
    sync_state, sync_error = await env.state()
    assert sync_state == "needs_resync"
    assert stored in sync_error
    # SDK 오류 원문은 저장값과 로그에 남지 않는다 (#485)
    assert "sensitive-marker" not in sync_error
    assert "sensitive-marker" not in caplog.text

    res = await _ask(env, _Q_PLAIN)
    assert res.status_code == 200, res.text
    assert res.json()["criteria_notice"] is None

    res = await _ask(env)
    assert res.status_code == 200, res.text
    assert "평가기준" in res.json()["criteria_notice"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cause, stored", _PERSISTENT)
async def test_analysis_stops_on_persistent_lookup_failure(
    env465, caplog, cause, stored
):
    """#469: 멈추고 저장하지 않으며 표시는 실패 응답 뒤에도 남는다."""
    env = env465
    _arm_persistent(env, cause)

    res, in_progress = await _analyze(env)

    assert res.status_code == 503, res.text
    assert "retry-after" not in res.headers
    assert (
        res.json()["detail"]
        == "평가기준 동기화가 필요합니다. 관리자에게 문의하세요."
    )
    assert (env.analysis_gens, env.saved, in_progress) == ([], [], False)
    assert await env.report_rows() == 0
    sync_state, sync_error = await env.state()
    assert sync_state == "needs_resync"
    assert stored in sync_error
    # SDK 오류 원문은 저장값과 로그에 남지 않는다 (#485)
    assert "sensitive-marker" not in sync_error
    assert "sensitive-marker" not in caplog.text

    # 관리자가 고친 뒤(상태는 needs_resync 그대로) 같은 업로드가 분석된다
    env.fake.corrupt, env.fake.active_fail = False, None
    res, _ = await _analyze(env)
    assert res.status_code == 200, res.text
    assert [g["filter"] for g in env.analysis_gens] == ['stable_id="SIDA"']
    assert (len(env.saved), await env.report_rows()) == (1, 1)


@pytest.mark.asyncio
async def test_missing_alias_document(env465):
    env = env465
    env.fake.no_alias = True

    res = await _ask(env)
    assert res.status_code == 200, res.text
    assert res.json()["criteria_notice"] == "활성 평가기준이 없습니다."

    res, in_progress = await _analyze(env)
    assert res.status_code == 500, res.text
    assert (env.analysis_gens, env.saved, in_progress) == ([], [], False)
    assert await env.state() == ("ok", None)


class _Clock:
    """GET 한 번에 논리 시간 10초, sleep 은 넘긴 값만큼 더한다."""

    def __init__(self):
        self.now = 0.0
        self.per_get = {}

    def sleep(self, seconds):
        self.now += seconds

    def flaky(self, fn, kind):
        # 각 GET 이 두 번 시간 초과로 실패하고 세 번째에 성공한다
        def call(*args, **kwargs):
            self.now += 10
            key = (kind, _SCOPE.get())
            n = self.per_get.get(key, 0)
            self.per_get[key] = n + 1
            if n % 3 < 2:
                raise _timeout()
            return fn(*args, **kwargs)

        return call


@pytest.mark.asyncio
async def test_analysis_lookup_retry_budget(env465, monkeypatch):
    from app.services import lessonplan_analysis_service as lpa_mod

    env = env465
    clock = _Clock()
    monkeypatch.setattr(time, "sleep", clock.sleep)
    stores = env.fake.file_search_stores
    stores.list = clock.flaky(stores.list, "stores")
    stores.documents.list = clock.flaky(stores.documents.list, "docs")
    at_generate = []
    real_generate = lpa_mod._call_gemini_with_file_search

    def generate(*args):
        at_generate.append(clock.now)
        return real_generate(*args)

    # 픽스처의 patch 보다 먼저 풀리도록 with 로 건다
    with patch.object(lpa_mod, "_call_gemini_with_file_search", generate):
        res, in_progress = await _analyze(env)

    assert res.status_code == 200, res.text
    # 스토어 1 + 활성 stores/docs 2 = 3 GET × (3 × 10 + 2 + 4)
    assert at_generate == [108]
    # 생성 뒤 보고서 표시 이름 조회 2 GET 이 더해져 조회만 180초
    assert clock.now == 180
    assert in_progress is False


@pytest.mark.asyncio
async def test_analysis_deadline_during_display_lookup(env465, monkeypatch):
    env = env465
    loop = asyncio.get_running_loop()
    real_timeout = asyncio.timeout
    delays, deadlines = [], []

    def fake_timeout(delay):
        delays.append(delay)
        deadlines.append(real_timeout(None))
        return deadlines[-1]

    entered, release = threading.Event(), threading.Event()
    stores = env.fake.file_search_stores
    real_list = stores.list

    def blocking_list(**kwargs):
        if _SCOPE.get()[:1] == ("display",):
            entered.set()
            loop.call_soon_threadsafe(
                lambda: deadlines[-1].reschedule(loop.time())
            )
            release.wait(5)
        return real_list(**kwargs)

    stores.list = blocking_list
    monkeypatch.setattr(asyncio, "timeout", fake_timeout)
    try:
        res = await env.client.post(
            "/api/lessonplan/analyze", json={"session_id": 1}
        )
    finally:
        release.set()
        monkeypatch.setattr(asyncio, "timeout", real_timeout)
    status_res = await env.client.get("/api/lessonplan/analyze/status")

    assert entered.is_set()
    assert delays == [180]
    assert res.status_code == 500, res.text
    assert res.json()["detail"] == "분석 시간 초과 (180초)"
    assert env.saved == []
    assert await env.report_rows() == 0
    assert await env.state() == ("ok", None)
    assert status_res.json()["in_progress"] is False


@pytest.mark.asyncio
async def test_qna_failure_service_logs_hide_sdk_text(env465, caplog):
    """#485: 생성 호출이 SDK 403 으로 실패해도 서비스 ERROR 로그에는 종류와 코드만 남는다."""
    env = env465

    def denied(**kwargs):
        raise _sdk(403)()

    env.fake.models.generate_content = denied

    res = await _ask(env)

    assert res.status_code == 500, res.text
    # 라우터 로그는 이 이슈 범위 밖이다. 서비스의 WARNING(traceback 포함)까지 본다
    service_text = "\n".join(
        logging.Formatter().format(r)
        for r in caplog.records
        if r.name.startswith("app.services.") and r.levelno >= logging.WARNING
    )
    assert "sensitive-marker" not in service_text
    assert "QnA 1패스 실패, 이중 도구로 폴백: ClientError 403" in service_text
    errors = {
        r.name.removeprefix("app.services."): logging.Formatter().format(r)
        for r in caplog.records
        if r.name.startswith("app.services.") and r.levelname == "ERROR"
    }
    assert errors == {
        "file_search_service": "검색 실패: ClientError 403",
        "criteria_vector_service": "평가기준 검색 실패: ClientError 403",
        "criteria_context_service": (
            "평가 기준 컨텍스트 검색 실패: ClientError 403"
        ),
        "qna_service": "QnA 처리 실패: ClientError 403",
    }


@pytest.mark.asyncio
async def test_qna_rubric_store_lookup_failure_hides_sdk_text(env465, caplog):
    """#485: 평가성 QnA 에서 평가기준 스토어 목록이 SDK 403 이어도 서비스 로그에 원문이 없다."""
    env = env465
    stores = env.fake.file_search_stores
    real_list = stores.list

    def denied_outside_scopes(**kwargs):
        if _SCOPE.get() == ():
            raise _sdk(403)()
        return real_list(**kwargs)

    stores.list = denied_outside_scopes

    res = await _ask(env)

    assert res.status_code == 500, res.text
    service_text = "\n".join(
        logging.Formatter().format(r)
        for r in caplog.records
        if r.name.startswith("app.services.") and r.levelno >= logging.WARNING
    )
    assert "예상치 못한 오류: ClientError 403" in service_text
    assert "sensitive-marker" not in service_text


@pytest.mark.asyncio
async def test_analysis_display_lookup_failure_hides_sdk_text(env465, caplog):
    """#485: 분석의 활성 평가기준 표시 이름 조회가 SDK 403 이어도 로그에 원문이 없다."""
    env = env465
    stores = env.fake.file_search_stores
    real_list = stores.list

    def denied_in_display(**kwargs):
        if _SCOPE.get()[:1] == ("display",):
            raise _sdk(403)()
        return real_list(**kwargs)

    stores.list = denied_in_display

    res = await env.client.post(
        "/api/lessonplan/analyze", json={"session_id": 1}
    )

    assert res.status_code == 200, res.text
    assert "(참고 문서 표시 생략): ClientError 403" in caplog.text
    assert "sensitive-marker" not in caplog.text
