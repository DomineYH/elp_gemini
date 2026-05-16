"""criteria_vector_service._string_list_metadata respects File Search 256-char limit (issue #60)."""
from app.services.criteria_vector_service import _string_list_metadata


def test_string_list_metadata_chunks_under_256_chars():
    """Multi-chunk string_list_value entries must each be <= 256 chars."""
    # Title large enough to force multi-chunk after base64.
    long_value = "A" * 5000
    meta = _string_list_metadata("original_title_b64", long_value)

    values = meta["string_list_value"]["values"]
    assert len(values) > 1, "test setup must force multi-chunk output"
    longest = max(len(v) for v in values)
    assert longest <= 256, (
        f"chunk length {longest} exceeds Google File Search "
        f"string_list_value 256-char limit"
    )
