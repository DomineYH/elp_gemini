"""alias-map 페이로드 base64 청크 인/디코딩"""
import json

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
    assert all(len(c) <= 3000 for c in chunks)
    assert decode_alias_map_payload(chunks)["entries"]["id1"]["alias"] == "한" * 10_000


def test_payload_key_is_stable():
    # Used elsewhere to identify the payload metadata entry; renaming requires migration
    assert ALIAS_MAP_PAYLOAD_KEY == "payload_b64"
