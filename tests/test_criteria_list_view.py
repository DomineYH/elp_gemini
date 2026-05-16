"""Criteria list view context mapping checks."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.routers.admin.criteria_views import _criteria_items_from_rows


def _row(
    *,
    stable_id: str | None,
    title: str,
    display_alias: str | None = None,
    status: str = "uploaded",
    document_id: str | None = None,
):
    return SimpleNamespace(
        stable_id=stable_id,
        title=title,
        display_alias=display_alias,
        status=status,
        created_at=datetime(2026, 5, 15, 3, 21, tzinfo=timezone.utc),
        document_id=document_id,
    )


def test_context_uses_criteria_items_list():
    items = _criteria_items_from_rows(
        [
            _row(
                stable_id="01HSTABLE100",
                title="orig.pdf",
                display_alias="my-alias",
                status="active",
                document_id="cloud-doc-123",
            )
        ]
    )

    assert isinstance(items, list)
    assert len(items) == 1
    item = items[0]
    assert item["stable_id"] == "01HSTABLE100"
    assert item["title"] == "orig.pdf"
    assert item["display_alias"] == "my-alias"
    assert item["status"] == "active"
    assert item["document_id"] == "cloud-doc-123"
    assert "created_at" in item

    for removed in (
        "cloud_documents",
        "cloud_error",
        "needs_sync",
        "pending_count",
        "cloud_sync_warning",
        "active_criteria",
    ):
        assert removed not in item


def test_criteria_items_skip_null_stable_id():
    items = _criteria_items_from_rows(
        [
            _row(stable_id=None, title="legacy.pdf"),
            _row(stable_id="01HSTABLE200", title="modern.pdf"),
        ]
    )

    assert len(items) == 1
    assert items[0]["title"] == "modern.pdf"
    assert items[0]["stable_id"] == "01HSTABLE200"


def test_criteria_items_marks_legacy_surrogate_rows():
    """legacy_ prefix를 가진 stable_id 행은 is_legacy=True로 표시되어야 한다."""
    rows = [
        SimpleNamespace(
            stable_id="legacy_abcdef0123456789",
            title="old.pdf",
            display_alias=None,
            status="uploaded",
            created_at=None,
            document_id="docs/old",
        ),
        SimpleNamespace(
            stable_id="01HV2REAL",
            title="new.pdf",
            display_alias=None,
            status="uploaded",
            created_at=None,
            document_id="docs/new",
        ),
    ]
    items = _criteria_items_from_rows(rows)
    by_sid = {i["stable_id"]: i for i in items}
    assert by_sid["legacy_abcdef0123456789"]["is_legacy"] is True
    assert by_sid["01HV2REAL"]["is_legacy"] is False
