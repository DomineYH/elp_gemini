"""Regression test for the two-pass analysis call (issue #118).

Pass 1 retrieves the lesson-plan text from the user store only. Pass 2
injects that text into the prompt and searches the rubric store only, so
the user store tool never sits next to the rubric tool (the combination
that made the model ignore the uploaded lesson plan in issue #86).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from google.genai import types

from app.services.lessonplan_analysis_service import (
    _call_gemini_with_file_search,
)

# #449: 1패스 응답은 검색 근거(grounding chunk)가 있어야 지도안 원문으로 본다
GROUNDED_PASS1 = SimpleNamespace(
    text="지도안 원문",
    candidates=[
        SimpleNamespace(
            grounding_metadata=SimpleNamespace(grounding_chunks=[object()])
        )
    ],
)


def _run(rubric_metadata_filter):
    client = MagicMock()
    client.models.generate_content.side_effect = [
        GROUNDED_PASS1,
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


def _pass1(text=None, chunks=0, finish_reason="STOP", parts=True):
    grounding = (
        types.GroundingMetadata(
            grounding_chunks=[
                types.GroundingChunk(
                    retrieved_context=types.GroundingChunkRetrievedContext(
                        title="plan.pdf"
                    )
                )
            ]
            * chunks
        )
        if chunks
        else None
    )
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=text)] if parts else None,
                ),
                finish_reason=finish_reason,
                grounding_metadata=grounding,
            )
        ]
    )


@pytest.mark.parametrize(
    "pass1",
    [
        _pass1("업로드된 수업 지도안 문서가 확인되지 않습니다."),
        _pass1(parts=False),
        _pass1("   \n", chunks=1),
        types.GenerateContentResponse(candidates=[]),
        types.GenerateContentResponse(
            prompt_feedback=types.GenerateContentResponsePromptFeedback(
                block_reason="SAFETY"
            )
        ),
        _pass1(parts=False, finish_reason="RECITATION"),
    ],
    ids=[
        "근거 없는 안내문",
        "parts 없음",
        "공백만",
        "후보 없음",
        "차단",
        "RECITATION",
    ],
)
def test_pass1_without_grounded_text_skips_evaluation(pass1, caplog):
    client = MagicMock()
    client.models.generate_content.side_effect = [pass1, Mock(text="보고서")]

    with caplog.at_level(
        "INFO", logger="app.services.lessonplan_analysis_service"
    ):
        result = _call_gemini_with_file_search.__wrapped__(
            client=client,
            model="gemini-test",
            contents="prompt",
            rubric_store_id="fileSearchStores/rubric-xxx",
            user_store_id="fileSearchStores/user-yyy",
            rubric_metadata_filter=None,
        )

    assert result is None
    assert client.models.generate_content.call_count == 1
    assert "분석 1패스 chars=" in caplog.text
    assert "확인되지 않습니다" not in caplog.text
