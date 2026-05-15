# tests/unit/test_require_criteria_sync_ready.py
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.dependencies import require_criteria_sync_ready


@pytest.mark.asyncio
async def test_passes_when_state_is_ok():
    repo = AsyncMock()
    repo.get = AsyncMock(return_value="ok")
    # Should not raise
    await require_criteria_sync_ready(app_state_repo=repo)


@pytest.mark.asyncio
async def test_blocks_when_state_is_error():
    repo = AsyncMock()
    repo.get = AsyncMock(return_value="error")
    with pytest.raises(HTTPException) as exc_info:
        await require_criteria_sync_ready(app_state_repo=repo)
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_blocks_when_state_is_needs_resync():
    repo = AsyncMock()
    repo.get = AsyncMock(return_value="needs_resync")
    with pytest.raises(HTTPException) as exc_info:
        await require_criteria_sync_ready(app_state_repo=repo)
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_blocks_when_state_is_missing():
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc_info:
        await require_criteria_sync_ready(app_state_repo=repo)
    assert exc_info.value.status_code == 503
