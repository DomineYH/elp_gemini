"""alias-map 페이로드 base64 청크 인/디코딩"""

from app.services.alias_map_codec import (
    encode_alias_map_payload,
    decode_alias_map_payload,
    ALIAS_MAP_PAYLOAD_KEY,
)


def test_roundtrip_korean_text():
    data = {"schema_version": 1, "entries": {"id1": {"alias": "한글", "status": "active"}}}
    chunks = encode_alias_map_payload(data)
    assert isinstance(chunks, list)
    assert all(isinstance(c, str) for c in chunks)

    decoded = decode_alias_map_payload(chunks)
    assert decoded == data


def test_chunks_are_bounded():
    # 10KB of Korean text
    big = {"entries": {"id1": {"alias": "한" * 10_000, "status": "uploaded"}}}
    chunks = encode_alias_map_payload(big)
    assert all(len(c) <= 256 for c in chunks)
    assert decode_alias_map_payload(chunks)["entries"]["id1"]["alias"] == "한" * 10_000


def test_payload_key_is_stable():
    # Used elsewhere to identify the payload metadata entry; renaming requires migration
    assert ALIAS_MAP_PAYLOAD_KEY == "payload_b64"


def test_chunks_respect_file_search_string_list_value_limit():
    """Google File Search rejects string_list_value entries > 256 chars (issue #60)."""
    # Force multi-chunk by encoding a payload that won't fit in a single chunk.
    big = {
        "schema_version": 1,
        "entries": {
            f"id{i}": {"alias": "한" * 100, "status": "uploaded"}
            for i in range(50)
        },
    }
    chunks = encode_alias_map_payload(big)
    assert len(chunks) > 1, "test setup must produce multi-chunk output"
    longest = max(len(c) for c in chunks)
    assert longest <= 256, (
        f"chunk length {longest} exceeds Google File Search "
        f"string_list_value 256-char limit"
    )
