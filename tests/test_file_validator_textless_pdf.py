"""
FileValidator가 텍스트 없는 PDF와 손상 PDF를 400으로 거부하는지 검증 (#249)
"""

import threading
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


def _upload(data: bytes, content_type="application/pdf") -> UploadFile:
    return UploadFile(
        file=BytesIO(data),
        filename="rubric.pdf",
        headers=Headers({"content-type": content_type}),
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


@pytest.mark.asyncio
async def test_validate_file_runs_validate_pdf_off_event_loop_thread(
    monkeypatch,
):
    # pypdf 추출이 이벤트 루프를 막지 않아야 한다 (#453)
    real = FileValidator.validate_pdf
    seen = []

    def recording(self, file, contents):
        seen.append(threading.get_ident())
        return real(self, file, contents)

    monkeypatch.setattr(FileValidator, "validate_pdf", recording)
    data = text_pdf()

    result = await FileValidator().validate_file(_upload(data))

    assert len(seen) == 1
    assert seen[0] != threading.get_ident()
    assert result["valid"] is True
    assert result["file_size"] == len(data)
    assert result["metadata"]["validated"] == "true"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data, content_type, error",
    [
        (b"%PDF-1.4\n" + b"x" * 13, "application/pdf", CORRUPT_MESSAGE),
        (
            text_pdf() + b"\n/Launch",
            "application/pdf",
            "외부 프로그램 실행이 포함된 PDF는 업로드할 수 없습니다",
        ),
        (text_pdf(), "text/plain", "PDF 파일만 업로드 가능합니다"),
    ],
    ids=["corrupt", "launch", "wrong-mime"],
)
async def test_validate_file_keeps_error_dict_from_thread(
    data, content_type, error
):
    # 스레드 안에서 난 HTTPException도 지금과 같은 dict로 돌아온다 (#453)
    result = await FileValidator().validate_file(_upload(data, content_type))
    assert result == {"valid": False, "error": error}
