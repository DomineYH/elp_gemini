"""AdminDeletionService 단위 테스트."""

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db import Base
from app.models.analysis_reports import AnalysisReport
from app.models.chat_messages import ChatMessage, MessageRole
from app.models.chat_sessions import ChatSession
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.simulation_session import SimulationSession
from app.models.users import User
from app.services.admin_deletion_service import AdminDeletionService
from tests.conftest import TestingSessionLocal, engine


@pytest.fixture(autouse=True)
def _isolate_file_dirs(tmp_path, monkeypatch):
    """실제 체크아웃의 업로드/보고서 디렉터리를 건드리지 않도록 막는다."""
    for name in (
        "LESSONPLAN_BASE_DIR",
        "STATIC_UPLOADS_DIR",
        "SIMULATION_REPORTS_DIR",
    ):
        monkeypatch.setattr(
            f"app.services.admin_deletion_service.{name}",
            str(tmp_path / "isolated" / name),
        )


@pytest_asyncio.fixture
async def db_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def _stub_file_search_service(monkeypatch):
    import app.services.file_search_service as fss_module

    class _NoopFSS:
        async def delete_store_by_display_name(self, display_name):
            return None

    monkeypatch.setattr(
        fss_module, "FileSearchService", lambda *a, **k: _NoopFSS()
    )


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
    static_uploads_dir = tmp_path / "app" / "static" / "uploads"
    static_uploads_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "app.services.admin_deletion_service.STATIC_UPLOADS_DIR",
        str(static_uploads_dir),
        raising=False,
    )
    _stub_file_search_service(monkeypatch)

    async with TestingSessionLocal() as db:
        admin = User(
            username="admin1",
            nickname="Admin",
            hashed_password="h",
            is_admin=True,
        )
        user = User(
            username="stu1",
            nickname="Student",
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

        user_upload_dir = static_uploads_dir / str(user.id)
        user_upload_dir.mkdir()
        dashboard_upload_file = user_upload_dir / "20260101000000_dashboard.pdf"
        dashboard_upload_file.write_bytes(b"%PDF-1.4\n")

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
            "dashboard_upload_file": dashboard_upload_file,
            "static_uploads_dir": static_uploads_dir,
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
    assert result["files_removed"] == 3
    assert not seeded["report_file"].exists()
    assert not seeded["lessonplan_file"].exists()
    assert not seeded["dashboard_upload_file"].exists()


@pytest.mark.asyncio
async def test_delete_user_cascades_lessonplan_upload_rows(seeded):
    async with TestingSessionLocal() as db:
        upload = LessonPlanUpload(
            user_id=seeded["user_id"],
            filename="stu1_20260101000000_uploaded.pdf",
            original_filename="uploaded.pdf",
            file_hash="b" * 64,
        )
        db.add(upload)
        await db.commit()
        upload_id = upload.id

    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        result = await service.delete_user(
            target_user_id=seeded["user_id"],
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True

    async with TestingSessionLocal() as db:
        remaining = await db.execute(
            select(LessonPlanUpload).where(LessonPlanUpload.id == upload_id)
        )
        assert remaining.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_user_keeps_lessonplan_referenced_by_other_user(
    db_tables, tmp_path, monkeypatch
):
    lessonplan_base = tmp_path / "data" / "lessonplan"
    lessonplan_base.mkdir(parents=True)
    monkeypatch.setattr(
        "app.services.admin_deletion_service.LESSONPLAN_BASE_DIR",
        str(lessonplan_base),
    )
    static_uploads_dir = tmp_path / "app" / "static" / "uploads"
    static_uploads_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "app.services.admin_deletion_service.STATIC_UPLOADS_DIR",
        str(static_uploads_dir),
        raising=False,
    )
    _stub_file_search_service(monkeypatch)

    shared_lessonplan = lessonplan_base / "shared_20260101000000_plan.pdf"
    shared_lessonplan.write_bytes(b"%PDF-1.4\n")

    async with TestingSessionLocal() as db:
        admin = User(
            username="admin1",
            nickname="Admin",
            hashed_password="h",
            is_admin=True,
        )
        user1 = User(
            username="stu1",
            nickname="Student One",
            hashed_password="h",
            is_admin=False,
        )
        user2 = User(
            username="stu2",
            nickname="Student Two",
            hashed_password="h",
            is_admin=False,
        )
        db.add_all([admin, user1, user2])
        await db.flush()

        db.add_all(
            [
                AnalysisReport(
                    user_id=user1.id,
                    lessonplan_filename=shared_lessonplan.name,
                    lessonplan_original_name="plan.pdf",
                    report_filename="missing1.md",
                    report_path=str(tmp_path / "missing1.md"),
                    latency_ms=100,
                ),
                AnalysisReport(
                    user_id=user2.id,
                    lessonplan_filename=shared_lessonplan.name,
                    lessonplan_original_name="plan.pdf",
                    report_filename="missing2.md",
                    report_path=str(tmp_path / "missing2.md"),
                    latency_ms=100,
                ),
            ]
        )
        await db.commit()
        await db.refresh(admin)
        await db.refresh(user1)

        service = AdminDeletionService(db)
        result = await service.delete_user(
            target_user_id=user1.id,
            current_admin_id=admin.id,
        )

    assert result["ok"] is True
    assert result["deleted"] == 1
    assert result["files_removed"] == 0
    assert shared_lessonplan.exists()


@pytest.mark.asyncio
async def test_delete_user_calls_file_search_cleanup(seeded, monkeypatch):
    import app.services.file_search_service as fss_module

    called_with = []

    class FakeFSS:
        async def delete_store_by_display_name(self, display_name):
            called_with.append(display_name)

    monkeypatch.setattr(
        fss_module, "FileSearchService", lambda *a, **k: FakeFSS()
    )

    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        await service.delete_user(
            target_user_id=seeded["user_id"],
            current_admin_id=seeded["admin_id"],
        )

    assert called_with == [f"user-{seeded['user_id']}-store"]


@pytest.mark.asyncio
async def test_delete_user_removes_orphaned_upload(seeded):
    async with TestingSessionLocal() as db:
        user = User(
            username="orphan1",
            nickname="Orphan",
            hashed_password="h",
            is_admin=False,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        orphan_dir = seeded["static_uploads_dir"] / str(user.id)
        orphan_dir.mkdir()
        orphan_file = orphan_dir / "20260101000000_orphan.pdf"
        orphan_file.write_bytes(b"%PDF-1.4\n")

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
async def test_delete_user_removes_lessonplan_orphan_without_report(
    db_tables, tmp_path, monkeypatch
):
    lessonplan_base = tmp_path / "data" / "lessonplan"
    lessonplan_base.mkdir(parents=True)
    monkeypatch.setattr(
        "app.services.admin_deletion_service.LESSONPLAN_BASE_DIR",
        str(lessonplan_base),
    )
    static_uploads_dir = tmp_path / "app" / "static" / "uploads"
    static_uploads_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "app.services.admin_deletion_service.STATIC_UPLOADS_DIR",
        str(static_uploads_dir),
        raising=False,
    )
    _stub_file_search_service(monkeypatch)

    async with TestingSessionLocal() as db:
        admin = User(
            username="admin1",
            nickname="Admin",
            hashed_password="h",
            is_admin=True,
        )
        user = User(
            username="lonely1",
            nickname="Lonely",
            hashed_password="h",
            is_admin=False,
        )
        db.add_all([admin, user])
        await db.commit()
        await db.refresh(admin)
        await db.refresh(user)

        orphan_dir = lessonplan_base / str(user.id)
        orphan_dir.mkdir()
        orphan_file = orphan_dir / "plan.pdf"
        orphan_file.write_bytes(b"%PDF-1.4\n")

        service = AdminDeletionService(db)
        result = await service.delete_user(
            target_user_id=user.id,
            current_admin_id=admin.id,
        )

    assert result["ok"] is True
    assert result["deleted"] == 1
    assert result["files_removed"] >= 1
    assert not orphan_file.exists()


@pytest.mark.asyncio
async def test_delete_user_skips_other_user_files(
    db_tables, tmp_path, monkeypatch
):
    lessonplan_base = tmp_path / "data" / "lessonplan"
    lessonplan_base.mkdir(parents=True)
    monkeypatch.setattr(
        "app.services.admin_deletion_service.LESSONPLAN_BASE_DIR",
        str(lessonplan_base),
    )
    static_uploads_dir = tmp_path / "app" / "static" / "uploads"
    static_uploads_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "app.services.admin_deletion_service.STATIC_UPLOADS_DIR",
        str(static_uploads_dir),
        raising=False,
    )
    _stub_file_search_service(monkeypatch)

    async with TestingSessionLocal() as db:
        admin = User(
            username="admin1",
            nickname="Admin",
            hashed_password="h",
            is_admin=True,
        )
        kim = User(
            username="kim",
            nickname="Kim",
            hashed_password="h",
            is_admin=False,
        )
        kim_teacher = User(
            username="kim_teacher",
            nickname="Kim Teacher",
            hashed_password="h",
            is_admin=False,
        )
        db.add_all([admin, kim, kim_teacher])
        await db.flush()

        kim_report_file = tmp_path / "kim.md"
        kim_report_file.write_text("# kim", encoding="utf-8")
        kim_lessonplan_file = lessonplan_base / "kim_plan.pdf"
        kim_lessonplan_file.write_bytes(b"%PDF-1.4\n")
        kim_dashboard_dir = static_uploads_dir / str(kim.id)
        kim_dashboard_dir.mkdir()
        kim_dashboard_file = kim_dashboard_dir / "20260101000000_dashboard.pdf"
        kim_dashboard_file.write_bytes(b"%PDF-1.4\n")

        other_report_file = tmp_path / "kim_teacher.md"
        other_report_file.write_text("# kim_teacher", encoding="utf-8")
        other_lessonplan_file = lessonplan_base / "kim_teacher_plan.pdf"
        other_lessonplan_file.write_bytes(b"%PDF-1.4\n")
        other_dashboard_dir = static_uploads_dir / str(kim_teacher.id)
        other_dashboard_dir.mkdir()
        other_dashboard_file = (
            other_dashboard_dir / "20260101000000_dashboard.pdf"
        )
        other_dashboard_file.write_bytes(b"%PDF-1.4\n")

        db.add_all(
            [
                AnalysisReport(
                    user_id=kim.id,
                    lessonplan_filename=kim_lessonplan_file.name,
                    lessonplan_original_name="plan.pdf",
                    report_filename=kim_report_file.name,
                    report_path=str(kim_report_file),
                    latency_ms=100,
                ),
                AnalysisReport(
                    user_id=kim_teacher.id,
                    lessonplan_filename=other_lessonplan_file.name,
                    lessonplan_original_name="plan.pdf",
                    report_filename=other_report_file.name,
                    report_path=str(other_report_file),
                    latency_ms=100,
                ),
            ]
        )
        await db.commit()

        service = AdminDeletionService(db)
        result = await service.delete_user(
            target_user_id=kim.id,
            current_admin_id=admin.id,
        )

    assert result["ok"] is True
    assert result["deleted"] == 1
    assert result["files_removed"] == 3
    assert not kim_report_file.exists()
    assert not kim_lessonplan_file.exists()
    assert not kim_dashboard_file.exists()
    assert other_report_file.exists()
    assert other_lessonplan_file.exists()
    assert other_dashboard_file.exists()


@pytest.mark.asyncio
async def test_delete_user_removes_simulation_feedback_report(
    db_tables, tmp_path, monkeypatch
):
    """#162: 시뮬레이션 피드백 .md와 reports/{user_id}/ 디렉터리 제거."""
    module = "app.services.admin_deletion_service"
    reports_dir = tmp_path / "app" / "static" / "reports"
    for name, path in [
        ("LESSONPLAN_BASE_DIR", tmp_path / "data" / "lessonplan"),
        ("STATIC_UPLOADS_DIR", tmp_path / "app" / "static" / "uploads"),
        ("SIMULATION_REPORTS_DIR", reports_dir),
    ]:
        path.mkdir(parents=True)
        monkeypatch.setattr(f"{module}.{name}", str(path), raising=False)
    _stub_file_search_service(monkeypatch)

    async with TestingSessionLocal() as db:
        admin = User(
            username="admin1",
            nickname="Admin",
            hashed_password="h",
            is_admin=True,
        )
        user = User(
            username="stu1",
            nickname="Student",
            hashed_password="h",
            is_admin=False,
        )
        other = User(
            username="stu2",
            nickname="Other",
            hashed_password="h",
            is_admin=False,
        )
        db.add_all([admin, user, other])
        await db.flush()

        report_files = []
        for owner in (user, other):
            upload = LessonPlanUpload(
                user_id=owner.id,
                filename=f"{owner.username}_20260101000000_plan.pdf",
                original_filename="plan.pdf",
                file_hash="c" * 64,
            )
            db.add(upload)
            await db.flush()
            report = reports_dir / str(owner.id) / "x_simulation_1_reports.md"
            report.parent.mkdir(parents=True)
            report.write_text("# 피드백", encoding="utf-8")
            report_files.append(report)
            db.add(
                SimulationSession(
                    user_id=owner.id,
                    upload_id=upload.id,
                    persona_count=2,
                    model_name="m",
                    feedback_report_path=str(report),
                )
            )
        await db.commit()
        report, other_report = report_files

        service = AdminDeletionService(db)
        result = await service.delete_user(
            target_user_id=user.id,
            current_admin_id=admin.id,
        )

    assert result["files_removed"] == 1
    assert report.exists() is False
    assert report.parent.exists() is False
    assert other_report.exists()


@pytest.mark.asyncio
async def test_delete_user_leaves_checkout_reports_dir(
    db_tables, tmp_path, monkeypatch
):
    """#162 리뷰: 테스트가 실제 app/static/reports/{id}/를 지우면 안 된다."""
    module = "app.services.admin_deletion_service"
    for name in ("LESSONPLAN_BASE_DIR", "STATIC_UPLOADS_DIR"):
        monkeypatch.setattr(f"{module}.{name}", str(tmp_path / name))
    _stub_file_search_service(monkeypatch)

    async with TestingSessionLocal() as db:
        admin = User(
            username="admin1", nickname="A", hashed_password="h", is_admin=True
        )
        user = User(
            username="stu1", nickname="S", hashed_password="h", is_admin=False
        )
        db.add_all([admin, user])
        await db.commit()

        checkout_dir = Path("app/static/reports") / str(user.id)
        created = [
            p for p in (checkout_dir.parent, checkout_dir) if not p.exists()
        ]
        checkout_dir.mkdir(parents=True, exist_ok=True)
        sentinel = checkout_dir / "sentinel_simulation.md"
        sentinel.write_text("keep", encoding="utf-8")
        try:
            await AdminDeletionService(db).delete_user(
                target_user_id=user.id, current_admin_id=admin.id
            )
            assert sentinel.exists()
        finally:
            sentinel.unlink(missing_ok=True)
            for path in reversed(created):
                if path.is_dir() and not any(path.iterdir()):
                    path.rmdir()


def test_unlink_files_skips_paths_outside_reports_dir(
    tmp_path, monkeypatch, caplog
):
    """#162 리뷰: SIMULATION_REPORTS_DIR 밖의 경로는 지우지 않는다."""
    reports_dir = tmp_path / "reports"
    inside = reports_dir / "1" / "x_simulation_1_reports.md"
    inside.parent.mkdir(parents=True)
    inside.write_text("in", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("out", encoding="utf-8")
    monkeypatch.setattr(
        "app.services.admin_deletion_service.SIMULATION_REPORTS_DIR",
        str(reports_dir),
    )

    with caplog.at_level("WARNING"):
        removed = AdminDeletionService(None)._unlink_files(
            {str(inside), str(outside), str(reports_dir / ".." / "outside.md")}
        )

    assert removed == 1
    assert not inside.exists()
    assert outside.exists()
    assert any("outside.md" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_delete_user_blocks_admin_target(seeded):
    """다른 관리자(서로 다른 id)를 삭제 시도하면 PermissionError."""
    async with TestingSessionLocal() as db:
        # 별도 admin 계정 생성하여 self-delete 가드와 분리한다.
        target_admin = User(
            username="admin_target",
            nickname="AdminTarget",
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
async def test_delete_analysis_report_keeps_shared_lessonplan(seeded):
    async with TestingSessionLocal() as db:
        shared_report_file = seeded["report_file"].parent / "shared.md"
        shared_report_file.write_text("# shared", encoding="utf-8")
        shared_report = AnalysisReport(
            user_id=seeded["user_id"],
            lessonplan_filename=seeded["lessonplan_file"].name,
            lessonplan_original_name="plan.pdf",
            report_filename=shared_report_file.name,
            report_path=str(shared_report_file),
            latency_ms=100,
        )
        db.add(shared_report)
        await db.commit()

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
    assert shared_report_file.exists()


@pytest.mark.asyncio
async def test_delete_analysis_report_keeps_shared_report_path(seeded):
    async with TestingSessionLocal() as db:
        shared_report = AnalysisReport(
            user_id=seeded["user_id"],
            lessonplan_filename=seeded["lessonplan_file"].name,
            lessonplan_original_name="plan.pdf",
            report_filename=seeded["report_file"].name,
            report_path=str(seeded["report_file"]),
            latency_ms=100,
        )
        db.add(shared_report)
        await db.commit()

        service = AdminDeletionService(db)
        result = await service.delete_analysis_report(
            report_id=seeded["report_id"],
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 1
    assert result["files_removed"] == 0
    assert seeded["report_file"].exists()


@pytest.mark.asyncio
async def test_delete_analysis_report_removes_unreferenced_lessonplan(seeded):
    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        result = await service.delete_analysis_report(
            report_id=seeded["report_id"],
            current_admin_id=seeded["admin_id"],
        )

    assert result["ok"] is True
    assert result["deleted"] == 1
    assert result["files_removed"] == 2
    assert not seeded["report_file"].exists()
    assert not seeded["lessonplan_file"].exists()


@pytest.mark.asyncio
async def test_delete_analysis_report_removes_synthetic_upload_legacy_file(
    seeded,
    tmp_path,
):
    legacy_file = (
        seeded["lessonplan_file"].parent / "stu1_20260102000000_legacy.pdf"
    )
    legacy_file.write_bytes(b"%PDF-1.4\n")
    assert not (seeded["static_uploads_dir"] / legacy_file.name).exists()
    report_file = tmp_path / "synthetic_report.md"
    report_file.write_text("# synthetic", encoding="utf-8")

    async with TestingSessionLocal() as db:
        upload = LessonPlanUpload(
            user_id=seeded["user_id"],
            filename=legacy_file.name,
            original_filename="legacy.pdf",
            file_hash=None,
        )
        db.add(upload)
        await db.flush()
        report = AnalysisReport(
            user_id=seeded["user_id"],
            lessonplan_filename=legacy_file.name,
            lessonplan_original_name="legacy.pdf",
            report_filename=report_file.name,
            report_path=str(report_file),
            upload_id=upload.id,
            latency_ms=100,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)
        upload_id = upload.id
        report_id = report.id

    async with TestingSessionLocal() as db:
        service = AdminDeletionService(db)
        resolved = service._resolve_lessonplan_path(
            legacy_file.name,
            user_id=seeded["user_id"],
            upload_id=upload_id,
        )
        result = await service.delete_analysis_report(
            report_id=report_id,
            current_admin_id=seeded["admin_id"],
        )

    assert resolved == legacy_file
    assert result["ok"] is True
    assert result["deleted"] == 1
    assert result["files_removed"] == 2
    assert not report_file.exists()
    assert not legacy_file.exists()


def test_resolve_lessonplan_path_prefers_dashboard_upload(
    tmp_path, monkeypatch
):
    lessonplan_base = tmp_path / "data" / "lessonplan"
    lessonplan_base.mkdir(parents=True)
    monkeypatch.setattr(
        "app.services.admin_deletion_service.LESSONPLAN_BASE_DIR",
        str(lessonplan_base),
    )
    static_uploads_dir = tmp_path / "app" / "static" / "uploads"
    static_uploads_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "app.services.admin_deletion_service.STATIC_UPLOADS_DIR",
        str(static_uploads_dir),
        raising=False,
    )
    filename = "stu1_20260101000000_plan.pdf"
    upload_file = static_uploads_dir / filename
    upload_file.write_bytes(b"%PDF-1.4\n")

    service = AdminDeletionService(db=None)

    assert (
        service._resolve_lessonplan_path(
            filename,
            user_id=1,
            upload_id=1,
        )
        == upload_file
    )


@pytest.mark.asyncio
async def test_bulk_delete_sessions_requires_ownership(seeded):
    """타 사용자 세션이 섞이면 0건 삭제 + ValueError."""
    async with TestingSessionLocal() as db:
        # 두 번째 사용자 + 세션 생성
        from app.models.chat_sessions import ChatSession
        from app.models.users import User

        other = User(
            username="stu2",
            nickname="S2",
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
    # seeded.report.md + r2.md + now-unreferenced lessonplan PDF = 3.
    assert result["files_removed"] == 3
    assert not seeded["report_file"].exists()
    assert not f2.exists()
    assert not seeded["lessonplan_file"].exists()


@pytest.mark.asyncio
async def test_bulk_delete_reports_keeps_shared_lessonplan(seeded, tmp_path):
    async with TestingSessionLocal() as db:
        f2 = tmp_path / "report2.md"
        f3 = tmp_path / "report3.md"
        f2.write_text("# r2", encoding="utf-8")
        f3.write_text("# r3", encoding="utf-8")
        r2 = AnalysisReport(
            user_id=seeded["user_id"],
            lessonplan_filename=seeded["lessonplan_file"].name,
            lessonplan_original_name="plan.pdf",
            report_filename=f2.name,
            report_path=str(f2),
            latency_ms=100,
        )
        r3 = AnalysisReport(
            user_id=seeded["user_id"],
            lessonplan_filename=seeded["lessonplan_file"].name,
            lessonplan_original_name="plan.pdf",
            report_filename=f3.name,
            report_path=str(f3),
            latency_ms=100,
        )
        db.add_all([r2, r3])
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
    assert result["files_removed"] == 2
    assert not seeded["report_file"].exists()
    assert not f2.exists()
    assert seeded["lessonplan_file"].exists()
    assert f3.exists()
