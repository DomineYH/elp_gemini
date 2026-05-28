"""Regression test for issue #86.

Ensures the lesson-plan analysis call orders the file_search tools so the
user-document store is searched first; reversing the order caused the model
to ignore the uploaded lesson plan and respond as if no document existed.
"""
from unittest.mock import MagicMock

from app.services.lessonplan_analysis_service import (
    _call_gemini_with_file_search,
)


def test_user_store_tool_precedes_rubric_tool():
    client = MagicMock()
    # __wrapped__ bypasses the tenacity retry decorator so the call runs once.
    _call_gemini_with_file_search.__wrapped__(
        client=client,
        model="gemini-test",
        contents="prompt",
        rubric_store_id="fileSearchStores/rubric-xxx",
        user_store_id="fileSearchStores/user-yyy",
        rubric_metadata_filter='stable_id="ABC"',
    )

    config = client.models.generate_content.call_args.kwargs["config"]
    tools = list(config.tools)
    assert len(tools) == 2, tools

    first_stores = list(tools[0].file_search.file_search_store_names)
    second_stores = list(tools[1].file_search.file_search_store_names)

    assert first_stores == ["fileSearchStores/user-yyy"], (
        "user store tool must come first so the model grounds in the "
        "uploaded lesson plan (issue #86)"
    )
    assert second_stores == ["fileSearchStores/rubric-xxx"]
    assert tools[1].file_search.metadata_filter == 'stable_id="ABC"'
    assert tools[0].file_search.metadata_filter in (None, "")


def test_rubric_metadata_filter_omitted_when_none():
    client = MagicMock()
    _call_gemini_with_file_search.__wrapped__(
        client=client,
        model="gemini-test",
        contents="prompt",
        rubric_store_id="fileSearchStores/rubric-xxx",
        user_store_id="fileSearchStores/user-yyy",
        rubric_metadata_filter=None,
    )

    config = client.models.generate_content.call_args.kwargs["config"]
    tools = list(config.tools)
    assert list(tools[0].file_search.file_search_store_names) == [
        "fileSearchStores/user-yyy"
    ]
    assert list(tools[1].file_search.file_search_store_names) == [
        "fileSearchStores/rubric-xxx"
    ]
    assert tools[1].file_search.metadata_filter in (None, "")
