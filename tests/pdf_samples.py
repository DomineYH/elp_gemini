"""
테스트용 PDF 바이트 생성기 (#249). PDF 파일은 저장소에 커밋하지 않는다.
"""

from io import BytesIO

from pypdf import PdfWriter


def _build_pdf(objects: list[bytes]) -> bytes:
    """1번부터 번호를 매긴 객체들로 xref가 맞는 PDF를 만든다."""
    out = b"%PDF-1.4\n"
    offsets = []
    for num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref_at
    return out


def _stream(data: bytes, extra: bytes = b"") -> bytes:
    return b"<< /Length %d %s>>\nstream\n" % (len(data), extra) + (
        data + b"\nendstream"
    )


def _one_page_pdf(resources: bytes, content: bytes, *extra: bytes) -> bytes:
    return _build_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources " + resources + b" /Contents 4 0 R >>",
            _stream(content),
            *extra,
        ]
    )


def text_pdf(text: str = "Lesson plan with enough text") -> bytes:
    """Helvetica Tj로 text를 그린 1페이지 PDF"""
    return _one_page_pdf(
        b"<< /Font << /F1 5 0 R >> >>",
        b"BT /F1 12 Tf 72 720 Td (" + text.encode("ascii") + b") Tj ET",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )


def image_only_pdf() -> bytes:
    """1x1 DeviceGray 이미지만 그리고 텍스트 연산자는 없는 PDF"""
    return _one_page_pdf(
        b"<< /XObject << /Im1 5 0 R >> >>",
        b"q 612 0 0 792 0 0 cm /Im1 Do Q",
        _stream(
            b"\x80",
            b"/Type /XObject /Subtype /Image /Width 1 /Height 1 "
            b"/ColorSpace /DeviceGray /BitsPerComponent 8 ",
        ),
    )


def blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()
