"""응답 스키마가 naive UTC datetime을 '+00:00' 오프셋으로 직렬화한다 (#163)."""

from datetime import datetime

from app.schemas.analysis_reports import AnalysisReportItem
from app.schemas.sessions import (
    ChatMessageResponse,
    CreateSessionResponse,
    UserSessionItem,
)

NAIVE = datetime(2026, 10, 21, 10, 36, 54)
EXPECTED = "2026-10-21T10:36:54+00:00"


def test_create_session_response_has_utc_offset():
    item = CreateSessionResponse(
        session_id=1,
        user_id=1,
        lessonplan_filename="lp.pdf",
        created_at=NAIVE,
    )
    assert item.model_dump(mode="json")["created_at"] == EXPECTED


def test_chat_message_response_has_utc_offset():
    item = ChatMessageResponse(
        id=1, session_id=1, role="user", content="q", created_at=NAIVE
    )
    assert item.model_dump(mode="json")["created_at"] == EXPECTED


def test_user_session_item_has_utc_offset():
    item = UserSessionItem(
        session_id=1,
        created_at=NAIVE,
        updated_at=NAIVE,
        last_message_at=NAIVE,
    )
    dumped = item.model_dump(mode="json")
    assert dumped["created_at"] == EXPECTED
    assert dumped["updated_at"] == EXPECTED
    assert dumped["last_message_at"] == EXPECTED


def test_user_session_item_keeps_missing_last_message_none():
    item = UserSessionItem(
        session_id=1,
        created_at=NAIVE,
        updated_at=NAIVE,
        last_message_at=None,
    )
    assert item.model_dump(mode="json")["last_message_at"] is None


def test_analysis_report_item_has_utc_offset():
    item = AnalysisReportItem(
        id=1,
        lessonplan_filename="lp.pdf",
        report_filename="r.md",
        report_path="app/static/reports/r.md",
        created_at=NAIVE,
    )
    assert item.model_dump(mode="json")["created_at"] == EXPECTED
