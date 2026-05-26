import asyncio
from contextlib import suppress

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.criteria import Criteria
from app.repositories.criteria_repository import CriteriaRepository


async def _keep_loop_awake():
    while True:
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_delete_by_stable_ids_except_prunes_null_stable_id_rows():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ticker = asyncio.create_task(_keep_loop_awake())

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            db.add_all([
                Criteria(
                    stable_id=None,
                    document_id="doc_legacy",
                    title="legacy.pdf",
                    file_size=1,
                    file_path="/tmp/legacy.pdf",
                    status="active",
                    uploaded_by="test",
                ),
                Criteria(
                    stable_id="sid_keep",
                    document_id="doc_keep",
                    title="keep.pdf",
                    file_size=1,
                    file_path="/tmp/keep.pdf",
                    status="active",
                    uploaded_by="test",
                ),
            ])
            await db.flush()

            deleted_count = await CriteriaRepository(
                db
            ).delete_by_stable_ids_except({"sid_keep"})

            result = await db.execute(
                select(Criteria).order_by(Criteria.id)
            )
            rows = list(result.scalars().all())

        assert deleted_count == 1
        assert [row.stable_id for row in rows] == ["sid_keep"]
    finally:
        await engine.dispose()
        ticker.cancel()
        with suppress(asyncio.CancelledError):
            await ticker
