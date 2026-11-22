"""지도안 추출문에서 NUL은 공백으로, 사설 영역 글자는 지운다 (#391)."""

from types import SimpleNamespace

import pytest

from app.services.simulation import lessonplan_source


def _extract(monkeypatch, tmp_path, pages):
    (tmp_path / "7").mkdir(exist_ok=True)
    (tmp_path / "7" / "plan.pdf").write_bytes(b"")
    monkeypatch.setattr(lessonplan_source, "UPLOADS_DIR", tmp_path)
    reader = SimpleNamespace(
        pages=[SimpleNamespace(extract_text=lambda t=t: t) for t in pages]
    )
    monkeypatch.setattr(lessonplan_source, "PdfReader", lambda _path: reader)
    upload = SimpleNamespace(user_id=7, filename="plan.pdf")
    return lessonplan_source.extract_text(upload)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("공공데이터를\x00활용해서", "공공데이터를 활용해서"),
        ("하기-\uf000 엑셀로", "하기- 엑셀로"),
        ("평범한 줄\n\t탭 다음 한글", "평범한 줄\n\t탭 다음 한글"),
        ("\ue000가\uf8ff나", "가나"),
        ("힣\uf900", "힣\uf900"),
        ("\x00\x00", "  "),
    ],
)
def test_extract_text_cleans_nul_and_private_use(
    monkeypatch, tmp_path, raw, expected
):
    assert _extract(monkeypatch, tmp_path, [raw]) == expected


def test_extract_text_joins_pages_even_when_one_is_none(monkeypatch, tmp_path):
    assert _extract(monkeypatch, tmp_path, [None, "둘째"]) == "\n둘째"
    assert _extract(monkeypatch, tmp_path, ["첫째", None]) == "첫째\n"


def test_extract_text_missing_file_is_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(lessonplan_source, "UPLOADS_DIR", tmp_path)
    upload = SimpleNamespace(user_id=7, filename="none.pdf")
    assert lessonplan_source.extract_text(upload) == ""
