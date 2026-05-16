"""
PR #57 의 rubric-metadata-store 잔재를 정리하는 일회성 마이그레이션.

스코프(최소):
- marker 검사 → 이미 끝났으면 no-op
- rubric-metadata-store가 존재하면 force=True로 삭제
- marker 기록

stable_id 백필(PDF 로컬 캐시가 있는 경우 재업로드)은 별도 옵션 작업으로 분리.
현재 운영에는 평가기준 PDF가 1-5개로 매우 적어, 관리자가 UI에서 재업로드하는 편이 안전.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

LEGACY_METADATA_STORE_NAME = "rubric-metadata-store"
MIGRATION_MARKER_KEY = "criteria_migration_v2_done"


async def migrate_from_legacy_manifest(*, client, app_state) -> None:
    if await app_state.get(MIGRATION_MARKER_KEY) == "true":
        return

    legacy = None
    for s in client.file_search_stores.list():
        if s.display_name == LEGACY_METADATA_STORE_NAME:
            legacy = s
            break

    if legacy is not None:
        logger.info(f"legacy rubric-metadata-store 발견 — 삭제: {legacy.name}")
        client.file_search_stores.delete(name=legacy.name, config={"force": True})

    await app_state.set(MIGRATION_MARKER_KEY, "true")
