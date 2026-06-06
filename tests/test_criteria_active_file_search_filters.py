"""Active criteria metadata filters for rubric File Search call sites."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories.app_state_repository import KEY_SYNC_STATE
from app.schemas.alias_map import AliasMap, AliasMapEntry


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
        text="제목: 미래 인구 예측 / 학습목표: ...", candidates=[]
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
    pass2_contents = (
        client.models.generate_content.call_args_list[1].kwargs["contents"]
    )
    assert "EVAL_PROMPT_BODY" in pass2_contents
    assert "미래 인구 예측" in pass2_contents


@pytest.mark.asyncio
async def test_lessonplan_analysis_skips_gemini_when_no_active_criteria():
    from app.services.lessonplan_analysis_service import (
        LessonPlanAnalysisService,
    )

    db = AsyncMock()
    client = MagicMock()

    with patch(
        "app.services.lessonplan_analysis_service.genai.Client",
        return_value=client,
    ), patch(
        "app.services.lessonplan_analysis_service.FileSearchService"
    ):
        service = LessonPlanAnalysisService(db)

    service._find_existing_report_for_latest_upload = AsyncMock(
        return_value=(
            SimpleNamespace(
                id=11,
                filename="lesson.pdf",
                original_filename="lesson.pdf",
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

    with patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value=None),
        create=True,
    ), patch(
        "app.services.lessonplan_analysis_service._call_gemini_with_file_search",
        return_value=SimpleNamespace(text="report", candidates=[]),
    ) as gemini_call:
        result = await service.analyze_lesson_plan(
            session_id=1,
            user_id=7,
        )

    assert result["success"] is False
    assert result["error_code"] == "NO_ACTIVE_CRITERIA"
    gemini_call.assert_not_called()


@pytest.mark.asyncio
async def test_lessonplan_analysis_continues_without_filter_when_active_filter_fails():
    from app.services.lessonplan_analysis_service import (
        LessonPlanAnalysisService,
    )

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    client = MagicMock()

    with patch(
        "app.services.lessonplan_analysis_service.genai.Client",
        return_value=client,
    ), patch(
        "app.services.lessonplan_analysis_service.FileSearchService"
    ), patch(
        "app.services.lessonplan_analysis_service.AppStateRepository",
        create=True,
    ) as state_cls:
        state = state_cls.return_value
        state.set = AsyncMock()
        service = LessonPlanAnalysisService(db)

        service._find_existing_report_for_latest_upload = AsyncMock(
            return_value=(
                SimpleNamespace(
                    id=11,
                    filename="lesson.pdf",
                    original_filename="lesson.pdf",
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

        with patch(
            "app.services.criteria_vector_service."
            "CriteriaVectorService.active_stable_id_filter",
            new=AsyncMock(side_effect=RuntimeError("alias map corrupt")),
            create=True,
        ), patch(
            "app.services.lessonplan_analysis_service.asyncio.to_thread",
            new=AsyncMock(
                return_value=SimpleNamespace(text="report", candidates=[])
            ),
        ) as gemini_call:
            result = await service.analyze_lesson_plan(
                session_id=1,
                user_id=7,
            )

    assert result["success"] is True
    assert result["criteria_notice"]
    assert "평가기준" in result["criteria_notice"]
    assert gemini_call.await_args.args[6] is None
    state.set.assert_any_await(KEY_SYNC_STATE, "needs_resync")


@pytest.mark.asyncio
async def test_qna_evaluation_filters_rubric_store_by_active_stable_id():
    from app.services.qna_service import QnAService

    db = AsyncMock()
    client = MagicMock()
    response = MagicMock()
    response.text = "answer"
    response.candidates = []
    client.models.generate_content.return_value = response

    with patch(
        "app.services.qna_service.genai.Client",
        return_value=client,
    ), patch(
        "app.services.qna_service.FileSearchService"
    ) as file_search_cls, patch(
        "app.services.criteria_context_service.build_criteria_context_or_notice",
        new=AsyncMock(return_value=(None, None)),
    ), patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value='stable_id="01HACTIVE"'),
        create=True,
    ):
        file_search = file_search_cls.return_value
        file_search.get_user_store_id = MagicMock(
            return_value="fileSearchStores/user"
        )
        file_search.get_dual_store_ids = MagicMock(
            return_value=["fileSearchStores/user", "fileSearchStores/rubric"]
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
    rubric_search = _file_search_for_store(config, "fileSearchStores/rubric")
    user_search = _file_search_for_store(config, "fileSearchStores/user")

    assert rubric_search is not None
    assert rubric_search.metadata_filter == 'stable_id="01HACTIVE"'
    assert user_search is not None
    assert getattr(user_search, "metadata_filter", None) is None


@pytest.mark.asyncio
async def test_qna_evaluation_skips_rubric_store_when_no_active_criteria():
    from app.services.qna_service import QnAService

    db = AsyncMock()
    client = MagicMock()
    response = MagicMock()
    response.text = "answer"
    response.candidates = []
    client.models.generate_content.return_value = response

    with patch(
        "app.services.qna_service.genai.Client",
        return_value=client,
    ), patch(
        "app.services.qna_service.FileSearchService"
    ) as file_search_cls, patch(
        "app.services.criteria_context_service.build_criteria_context_or_notice",
        new=AsyncMock(return_value=(None, None)),
    ), patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(return_value=None),
        create=True,
    ):
        file_search = file_search_cls.return_value
        file_search.get_user_store_id = MagicMock(
            return_value="fileSearchStores/user"
        )
        file_search.get_dual_store_ids = MagicMock(
            return_value=["fileSearchStores/user", "fileSearchStores/rubric"]
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
    client = MagicMock()
    response = MagicMock()
    response.text = "answer"
    response.candidates = []
    client.models.generate_content.return_value = response

    with patch(
        "app.services.qna_service.genai.Client",
        return_value=client,
    ), patch(
        "app.services.qna_service.FileSearchService"
    ) as file_search_cls, patch(
        "app.services.criteria_context_service.build_criteria_context_or_notice",
        new=AsyncMock(return_value=(None, None)),
    ), patch(
        "app.repositories.app_state_repository.AppStateRepository"
    ) as state_cls, patch(
        "app.services.criteria_vector_service."
        "CriteriaVectorService.active_stable_id_filter",
        new=AsyncMock(side_effect=RuntimeError("alias map corrupt")),
        create=True,
    ):
        state = state_cls.return_value
        state.set = AsyncMock()
        file_search = file_search_cls.return_value
        file_search.get_user_store_id = MagicMock(
            return_value="fileSearchStores/user"
        )
        file_search.get_dual_store_ids = MagicMock(
            return_value=["fileSearchStores/user", "fileSearchStores/rubric"]
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
