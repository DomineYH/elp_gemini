"""AdminDeletionService 단위 테스트."""
from pathlib import Path

import pytest
import pytest_asyncio

from app.db import Base
from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.models.users import User
from app.services.admin_deletion_service import AdminDeletionService
from tests.conftest import TestingSessionLocal, engine


@pytest_asyncio.fixture
async def db_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def seeded(db_tables, tmp_path, monkeypatch):
    """관리자 + 일반 사용자 + 세션 + 보고서 시드.

    프로덕션과 동일하게 lessonplan_filename은 bare filename으로 저장하고
    LESSONPLAN_BASE_DIR을 tmp_path의 lessonplan 디렉터리로 patch한다.
    """
    lessonplan_base = tmp_path / "data" / "lessonplan"
    lessonplan_base.mkdir(parents=True)
    monkeypatch.setattr(
        "app.services.admin_deletion_service.LESSONPLAN_BASE_DIR",
        str(lessonplan_base),
    )

    async with TestingSessionLocal() as db:
        admin = User(
            username="admin1",
            nickname="Admin",
            email="admin@test.com",
            hashed_password="h",
            is_admin=True,
        )
        user = User(
            username="stu1",
            nickname="Student",
            email="stu1@test.com",
            hashed_password="h",
            is_admin=False,
        )
        db.add_all([admin, user])
        await db.flush()

        session = ChatSession(
            user_id=user.id,
            user_type="1학년",
            title="대화A",
        )
        db.add(session)
        await db.flush()

        msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.USER,
            content="질문",
        )
        db.add(msg)

        # 실제 파일을 생성하여 삭제 검증에 사용
        report_file = tmp_path / "report.md"
        report_file.write_text("# 보고서", encoding="utf-8")

        lessonplan_filename = "stu1_20260101000000_plan.pdf"
        lessonplan_file = lessonplan_base / lessonplan_filename
        lessonplan_file.write_bytes(b"%PDF-1.4\n")

        report = AnalysisReport(
            user_id=user.id,
            # 프로덕션 컨벤션: bare filename
            lessonplan_filename=lessonplan_filename,
            lessonplan_original_name="plan.pdf",
            report_filename=report_file.name,
            report_path=str(report_file),
            latency_ms=1000,
        )
        db.add(report)
        await db.commit()

        yield {
            "admin_id": admin.id,
            "user_id": user.id,
            "session_id": session.id,
            "report_id": report.id,
            "report_file": report_file,
            "lessonplan_file": lessonplan_file,
        }


@pytest.mark.asyncio
async def test_delete_user_cascades_and_removes_files(seeded):
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        result = await service.delete_user(
            target_user_id=seeded["user_id"],
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 1
    assert result["files_removed"] == 2  # report.md + lessonplan.pdf
    assert not seeded["report_file"].exists()
    assert not seeded["lessonplan_file"].exists()


@pytest.mark.asyncio
async def test_delete_user_removes_orphaned_upload(seeded):
    orphan_file = (
        seeded["lessonplan_file"].parent
        / "orphan1_20260101000000_orphan.pdf"
    )
    orphan_file.write_bytes(b"%PDF-1.4\n")

    async with TestingSessionLocal() as db:
        user = User(
            username="orphan1",
            nickname="Orphan",
            email="orphan1@test.com",
            hashed_password="h",
            is_admin=False,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        service = AdminDeletionService(db)
        result = await service.delete_user(
            target_user_id=user.id,
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 1
    assert result["files_removed"] == 1
    assert not orphan_file.exists()


@pytest.mark.asyncio
async def test_delete_user_blocks_admin_target(seeded):
    """다른 관리자(서로 다른 id)를 삭제 시도하면 PermissionError."""
    async with TestingSessionLocal() as db:
        # 별도 admin 계정 생성하여 self-delete 가드와 분리한다.
        target_admin = User(
            username="admin_target",
            nickname="AdminTarget",
            email="admin_target@test.com",
            hashed_password="h",
            is_admin=True,
        )
        db.add(target_admin)
        await db.commit()
        await db.refresh(target_admin)

        service = AdminDeletionService(db)
        with pytest.raises(PermissionError, match="관리자 계정"):
            await service.delete_user(
                target_user_id=target_admin.id,
                current_admin_id=seeded["admin_id"],
            )


@pytest.mark.asyncio
async def test_delete_user_blocks_self(seeded):
    """관리자가 자기 자신을 지우려는 경우 PermissionError."""
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        with pytest.raises(PermissionError, match="자기 자신"):
            await service.delete_user(
                target_user_id=seeded["admin_id"],
                current_admin_id=seeded["admin_id"],
            )


@pytest.mark.asyncio
async def test_delete_user_not_found(seeded):
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        with pytest.raises(LookupError):
            await service.delete_user(
                target_user_id=99999,
                current_admin_id=seeded["admin_id"],
            )


@pytest.mark.asyncio
async def test_delete_chat_session_cascades_messages(seeded):
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        result = await service.delete_chat_session(
            session_id=seeded["session_id"],
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 1

    async with TestingSessionLocal() as db:
        from sqlalchemy import select
        from app.models.chat_messages import ChatMessage
        msg_rows = await db.execute(select(ChatMessage))
        assert msg_rows.scalars().all() == []


@pytest.mark.asyncio
async def test_delete_chat_session_not_found(seeded):
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        with pytest.raises(LookupError):
            await service.delete_chat_session(
                session_id=99999,
                current_admin_id=seeded["admin_id"],
            )


@pytest.mark.asyncio
async def test_delete_analysis_report_does_not_touch_lessonplan(seeded):
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        result = await service.delete_analysis_report(
            report_id=seeded["report_id"],
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 1
    assert result["files_removed"] == 1
    assert not seeded["report_file"].exists()
    assert seeded["lessonplan_file"].exists()


@pytest.mark.asyncio
async def test_bulk_delete_sessions_requires_ownership(seeded):
    """타 사용자 세션이 섞이면 0건 삭제 + ValueError."""
    async with TestingSessionLocal() as db:
        # 두 번째 사용자 + 세션 생성
        from app.models.users import User
        from app.models.chat_sessions import ChatSession
        other = User(
            username="stu2",
            nickname="S2",
            email="s2@test.com",
            hashed_password="h",
            is_admin=False,
        )
        db.add(other)
        await db.flush()
        other_session = ChatSession(
            user_id=other.id, user_type="1학년", title="B"
        )
        db.add(other_session)
        await db.commit()
        await db.refresh(other_session)

        service = AdminDeletionService(db)
        with pytest.raises(ValueError):
            await service.bulk_delete_sessions(
                user_id=seeded["user_id"],
                session_ids=[seeded["session_id"], other_session.id],
                current_admin_id=seeded["admin_id"],
            )


@pytest.mark.asyncio
async def test_bulk_delete_sessions_happy(seeded):
    async with TestingSessionLocal() as db:
        # 두 번째 세션 추가
        from app.models.chat_sessions import ChatSession
        s2 = ChatSession(
            user_id=seeded["user_id"], user_type="2학년", title="B"
        )
        db.add(s2)
        await db.commit()
        await db.refresh(s2)
        ids = [seeded["session_id"], s2.id]

        service = AdminDeletionService(db)
        result = await service.bulk_delete_sessions(
            user_id=seeded["user_id"],
            session_ids=ids,
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 2


@pytest.mark.asyncio
async def test_bulk_delete_reports_happy(seeded, tmp_path):
    async with TestingSessionLocal() as db:
        from app.models.analysis_reports import AnalysisReport
        f2 = tmp_path / "report2.md"
        f2.write_text("# r2", encoding="utf-8")
        r2 = AnalysisReport(
            user_id=seeded["user_id"],
            lessonplan_filename="",  # 빈 값 — 파일 미삭제
            lessonplan_original_name="b.pdf",
            report_filename=f2.name,
            report_path=str(f2),
            latency_ms=100,
        )
        db.add(r2)
        await db.commit()
        await db.refresh(r2)

        service = AdminDeletionService(db)
        result = await service.bulk_delete_reports(
            user_id=seeded["user_id"],
            report_ids=[seeded["report_id"], r2.id],
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 2
    # seeded.report.md + r2.md = 2; lessonplan PDF는 보존한다.
    assert result["files_removed"] == 2
    assert not seeded["report_file"].exists()
    assert not f2.exists()
    assert seeded["lessonplan_file"].exists()
