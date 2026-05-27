import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_state import AppState

logger = logging.getLogger(__name__)

KEY_API_KEY_HASH = "criteria_api_key_hash"
KEY_LAST_SYNCED_AT = "criteria_last_synced_at"
KEY_SYNC_STATE = "criteria_sync_state"
KEY_SYNC_ERROR = "criteria_sync_error"
KEY_LAST_ALIAS_MAP_UPDATED_AT = "criteria_last_alias_map_updated_at"

SYNC_STATE_OK = "ok"
SYNC_STATE_NEEDS_RESYNC = "needs_resync"
SYNC_STATE_ERROR = "error"


class AppStateRepository:
    """app_state 테이블 read/write."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, key: str) -> Optional[str]:
        stmt = select(AppState).where(AppState.key == key)
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        return row.value if row else None

    async def set(self, key: str, value: Optional[str]) -> None:
        stmt = select(AppState).where(AppState.key == key)
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if value is None:
            if row is not None:
                await self.db.delete(row)
            await self.db.flush()
            return

        if row is None:
            self.db.add(AppState(key=key, value=value))
        else:
            row.value = value
        await self.db.flush()

    async def set_many(self, items: dict[str, Optional[str]]) -> None:
        for k, v in items.items():
            await self.set(k, v)
