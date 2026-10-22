"""Regression test for the two-pass analysis call (issue #118).

Pass 1 retrieves the lesson-plan text from the user store only. Pass 2
injects that text into the prompt and searches the rubric store only, so
the user store tool never sits next to the rubric tool (the combination
that made the model ignore the uploaded lesson plan in issue #86).
"""

from unittest.mock import MagicMock, Mock

from app.services.lessonplan_analysis_service import (
    _call_gemini_with_file_search,
)


def _run(rubric_metadata_filter):
    client = MagicMock()
    client.models.generate_content.side_effect = [
        Mock(text="지도안 원문"),
        Mock(text="보고서"),
    ]
    # __wrapped__ bypasses the tenacity retry decorator so the call runs once.
    _call_gemini_with_file_search.__wrapped__(
        client=client,
        model="gemini-test",
        contents="prompt",
        rubric_store_id="fileSearchStores/rubric-xxx",
        user_store_id="fileSearchStores/user-yyy",
        rubric_metadata_filter=rubric_metadata_filter,
    )
    calls = client.models.generate_content.call_args_list
    assert len(calls) == 2, calls
    return calls


def _file_searches(call):
    return [tool.file_search for tool in call.kwargs["config"].tools]


def test_pass1_user_store_then_pass2_rubric_only():
    calls = _run('stable_id="ABC"')

    (first,) = _file_searches(calls[0])
    assert list(first.file_search_store_names) == ["fileSearchStores/user-yyy"]
    assert first.metadata_filter in (None, "")

    (second,) = _file_searches(calls[1])
    assert list(second.file_search_store_names) == [
        "fileSearchStores/rubric-xxx"
    ]
    assert second.metadata_filter == 'stable_id="ABC"'
    assert "지도안 원문" in calls[1].kwargs["contents"]


def test_rubric_metadata_filter_omitted_when_none():
    calls = _run(None)

    (second,) = _file_searches(calls[1])
    assert list(second.file_search_store_names) == [
        "fileSearchStores/rubric-xxx"
    ]
    assert second.metadata_filter in (None, "")
