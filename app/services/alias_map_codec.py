"""
alias-map 페이로드를 base64 청크로 인/디코딩한다.

이유:
- File Search custom_metadata의 string_value는 ASCII로 변환되므로 한글 손실
- 코드의 _manifest_payload_metadata 패턴을 그대로 따와 base64 + string_list_value 청크
"""
from __future__ import annotations

import base64
import json
from typing import Iterable, List


ALIAS_MAP_PAYLOAD_KEY = "payload_b64"
# Google File Search caps each string_list_value entry at 256 chars (issue #60).
# Keep in sync with file_search_service._MANIFEST_PAYLOAD_CHUNK_SIZE.
_CHUNK_SIZE = 240


def encode_alias_map_payload(data: dict) -> List[str]:
    """JSON 직렬화 → UTF-8 → base64 → 240자 청크 리스트."""
    encoded = base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii")
    if not encoded:
        return [""]
    return [encoded[i:i + _CHUNK_SIZE] for i in range(0, len(encoded), _CHUNK_SIZE)]


def decode_alias_map_payload(chunks: Iterable[str]) -> dict:
    """청크 리스트 → 결합 → base64 디코드 → UTF-8 → JSON parse."""
    joined = "".join(chunks or [])
    if not joined:
        return {}
    return json.loads(base64.b64decode(joined).decode("utf-8"))
