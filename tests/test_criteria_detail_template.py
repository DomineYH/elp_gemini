"""criteria_detail template rendering checks without ASGI/TestClient."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.templating import templates


def _criteria(display_alias: str | None, **overrides):
    # 실제 Criteria 모델 컬럼만 쓴다 (mime_type·vector_store_id는 없음, #186)
    fields = dict(
        id=1,
        title="orig.pdf",
        display_alias=display_alias,
        status="active",
        document_id="fileSearchStores/rubric/documents/doc-1",
        stable_id="01HSTABLE001",
        file_path="",
        file_size=0,
        uploaded_by="admin",
        created_at=datetime(2026, 5, 15, 3, 20, tzinfo=timezone.utc),
        synced_at=datetime(2026, 5, 15, 3, 21, tzinfo=timezone.utc),
        activated_at=None,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _render(criteria) -> str:
    # 앱과 같은 환경으로 그린다: kst 필터가 여기에만 등록돼 있다 (#448)
    template = templates.env.get_template("admin/criteria_detail.html")
    return template.render(
        user=SimpleNamespace(is_admin=True, email="admin@example.com"),
        criteria=criteria,
    )


def test_detail_shows_display_alias():
    text = _render(_criteria(display_alias="detail-alias"))

    assert "표시명: detail-alias" in text


def test_detail_hides_alias_line_when_null():
    text = _render(_criteria(display_alias=None))

    assert "표시명:" not in text


def test_detail_shows_real_metadata_and_hides_missing_file_fields():
    """클라우드 동기화 행: 빈 파일 경로·0 bytes·없는 MIME/Vector Store 숨김."""
    text = _render(_criteria(display_alias=None))

    assert "01HSTABLE001" in text
    assert "fileSearchStores/rubric/documents/doc-1" in text
    assert "2026-05-15 12:21:00" in text  # synced_at (KST)
    assert "admin" in text
    for gone in ("MIME 타입", "Vector Store ID", "0.00 MB", "파일 경로"):
        assert gone not in text, gone


def test_detail_shows_file_fields_when_present():
    text = _render(
        _criteria(
            display_alias=None,
            file_path="/data/c.pdf",
            file_size=2 * 1024 * 1024,
        )
    )

    assert "/data/c.pdf" in text
    assert "2.00 MB (2,097,152 bytes)" in text


def test_detail_renders_real_model_instance():
    """SimpleNamespace가 아닌 실제 모델로도 렌더된다 (없는 속성 참조 금지)."""
    from jinja2 import StrictUndefined

    from app.models.criteria import Criteria

    row = Criteria(
        id=2,
        title="rubric.pdf",
        document_id="fileSearchStores/r/documents/d",
        file_size=0,
        file_path="",
        status="active",
        uploaded_by="cloud",
        stable_id="01HREAL",
        display_alias=None,
        created_at=datetime(2026, 10, 21, 9, 0),
        synced_at=None,
        activated_at=None,
    )
    # overlay: 앱 환경의 필터·전역은 그대로 쓰고 undefined만 엄격하게 바꾼다
    env = templates.env.overlay(undefined=StrictUndefined)
    text = env.get_template("admin/criteria_detail.html").render(
        user=SimpleNamespace(is_admin=True, nickname="admin"),
        criteria=row,
        app_version="test",
        request=SimpleNamespace(
            session={}, url=SimpleNamespace(path="/admin/criteria/2")
        ),
    )
    assert "01HREAL" in text
    assert "rubric.pdf" in text
    assert "2026-10-21 18:00:00" in text  # created_at 09:00 UTC → KST


def test_detail_shows_times_in_kst_and_dash_when_missing():
    """생성일은 초까지 KST로, 값이 없는 활성화 시각은 '-'로 보인다 (#448)."""
    text = _render(
        _criteria(
            display_alias=None,
            created_at=datetime(2026, 11, 25, 1, 57, 23),
            synced_at=None,
            activated_at=None,
        )
    )

    assert "2026-11-25 10:57:23" in text
    assert "2026-11-25 01:57:23" not in text
    after = text[text.index("활성화 시각") :]
    assert after.split("<dd")[1].split(">")[1].split("<")[0].strip() == "-"
