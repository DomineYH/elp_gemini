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


@pytest.mark.asyncio
async def test_delete_by_stable_ids_except_dedupes_kept_stable_ids():
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
            dup_rows = [
                Criteria(
                    stable_id="abc",
                    document_id=f"doc_{index}",
                    title=f"abc_{index}.pdf",
                    file_size=1,
                    file_path=f"/tmp/abc_{index}.pdf",
                    status="active",
                    uploaded_by=f"uploader_{index}",
                )
                for index in range(1, 4)
            ]
            db.add_all(dup_rows)
            await db.flush()
            assert [row.id for row in dup_rows] == [1, 2, 3]

            deleted_count = await CriteriaRepository(
                db
            ).delete_by_stable_ids_except({"abc"})

            result = await db.execute(
                select(Criteria).where(Criteria.stable_id == "abc")
            )
            rows = list(result.scalars().all())

        assert deleted_count == 2
        assert len(rows) == 1
        assert rows[0].id == 1
        assert rows[0].uploaded_by == "uploader_1"
    finally:
        await engine.dispose()
        ticker.cancel()
        with suppress(asyncio.CancelledError):
            await ticker


@pytest.mark.asyncio
async def test_delete_by_stable_ids_except_combines_null_drop_and_dedupe():
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
                    document_id="doc_null_1",
                    title="null_1.pdf",
                    file_size=1,
                    file_path="/tmp/null_1.pdf",
                    status="active",
                    uploaded_by="null_1",
                ),
                Criteria(
                    stable_id=None,
                    document_id="doc_null_2",
                    title="null_2.pdf",
                    file_size=1,
                    file_path="/tmp/null_2.pdf",
                    status="active",
                    uploaded_by="null_2",
                ),
                Criteria(
                    stable_id="keep_me",
                    document_id="doc_keep_1",
                    title="keep_1.pdf",
                    file_size=1,
                    file_path="/tmp/keep_1.pdf",
                    status="active",
                    uploaded_by="keep_first",
                ),
                Criteria(
                    stable_id="keep_me",
                    document_id="doc_keep_2",
                    title="keep_2.pdf",
                    file_size=1,
                    file_path="/tmp/keep_2.pdf",
                    status="active",
                    uploaded_by="keep_second",
                ),
                Criteria(
                    stable_id="drop_me",
                    document_id="doc_drop",
                    title="drop.pdf",
                    file_size=1,
                    file_path="/tmp/drop.pdf",
                    status="active",
                    uploaded_by="drop",
                ),
            ])
            await db.flush()

            deleted_count = await CriteriaRepository(
                db
            ).delete_by_stable_ids_except({"keep_me"})

            result = await db.execute(select(Criteria).order_by(Criteria.id))
            rows = list(result.scalars().all())

        assert deleted_count == 4
        assert len(rows) == 1
        assert rows[0].stable_id == "keep_me"
        assert rows[0].uploaded_by == "keep_first"
    finally:
        await engine.dispose()
        ticker.cancel()
        with suppress(asyncio.CancelledError):
            await ticker
