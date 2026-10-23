"""
FileValidator가 텍스트 없는 PDF와 손상 PDF를 400으로 거부하는지 검증 (#249)
"""

from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.services.file_validator import FileValidator
from tests.pdf_samples import blank_pdf, image_only_pdf, text_pdf

TEXTLESS_MESSAGE = (
    "이미지(스캔)로만 된 PDF는 올릴 수 없습니다. "
    "텍스트를 선택·복사할 수 있는 PDF를 올려 주세요."
)
CORRUPT_MESSAGE = "PDF 파일이 손상되었거나 비어 있습니다."


def _upload(data: bytes) -> UploadFile:
    return UploadFile(
        file=BytesIO(data),
        filename="rubric.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )


def _validate(data: bytes):
    return FileValidator().validate_pdf(_upload(data), data)


@pytest.mark.parametrize(
    "data",
    [blank_pdf(), image_only_pdf(), text_pdf("x" * 10 + " " + "x" * 9)],
    ids=["blank", "image-only", "19-chars"],
)
def test_textless_pdf_rejected(data):
    with pytest.raises(HTTPException) as exc:
        _validate(data)
    assert exc.value.status_code == 400
    assert exc.value.detail == TEXTLESS_MESSAGE


@pytest.mark.parametrize(
    "data",
    [text_pdf(), text_pdf("x" * 10 + " " + "x" * 10)],
    ids=["text", "20-chars"],
)
def test_text_pdf_passes(data):
    file_size, metadata = _validate(data)
    assert file_size == len(data)
    assert metadata["validated"] == "true"


@pytest.mark.parametrize(
    "data",
    [b"%PDF-1.4\n" + b"x" * 13, text_pdf()[: len(text_pdf()) // 2]],
    ids=["header-only-22B", "half-truncated"],
)
def test_corrupt_pdf_rejected(data):
    with pytest.raises(HTTPException) as exc:
        _validate(data)
    assert exc.value.status_code == 400
    assert exc.value.detail == CORRUPT_MESSAGE


@pytest.mark.asyncio
async def test_validate_file_returns_textless_message():
    # 관리자 평가기준 라우트는 이 error를 그대로 400 detail로 쓴다
    result = await FileValidator().validate_file(_upload(blank_pdf()))
    assert result == {"valid": False, "error": TEXTLESS_MESSAGE}
