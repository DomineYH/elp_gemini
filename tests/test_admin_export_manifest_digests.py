"""#187: manifest 크기·해시, 시뮬레이션 항목, 보고서 삭제 시 원본 보존."""

import csv
import hashlib
import io
import zipfile
from datetime import datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.db import Base
from app.models.analysis_reports import AnalysisReport
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.simulation_session import SimulationSession
from app.models.users import User
from app.schemas.admin_export import ExportFilters
from app.services.admin_deletion_service import AdminDeletionService
from app.services.admin_export_service import (
    AdminExportService,
    ExportPlan,
    LessonplanEntry,
    ReportEntry,
    SimulationEntry,
    SimulationReportEntry,
    UserContext,
    build_readme,
)
from tests.conftest import TestingSessionLocal, engine

NOW = datetime(2026, 10, 21, 9, 0)


def _plan(tmp_path, include=None) -> ExportPlan:
    report_md = tmp_path / "r.md"
    report_md.write_bytes("# 보고서".encode("utf-8"))
    filters = (
        ExportFilters()
        if include is None
        else ExportFilters(include=frozenset(include))
    )
    utter = SimpleNamespace(
        seq=1,
        phase_idx=0,
        speaker_type="teacher",
        persona_id=None,
        target_persona_id=None,
        content="안녕하세요",
        structured=None,
        model_name="m",
        latency_ms=1,
        created_at=NOW,
    )
    return ExportPlan(
        users=[UserContext(user_id=4, filename_prefix="u00004")],
        reports=[
            ReportEntry(
                kind="report",
                user_id=4,
                resource_id=1,
                session_id=None,
                created_at=NOW,
                original_name="lesson.pdf",
                archive_path="reports/u00004__report_3__lesson.md",
                source_path=str(report_md),
                upload_id=3,
            )
        ],
        lessonplans=[
            LessonplanEntry(
                kind="lessonplan",
                user_id=4,
                resource_id=3,
                session_id=None,
                created_at=NOW,
                original_name="lesson.pdf",
                archive_path="lessonplans/u00004__lessonplan_3__lesson.pdf",
                source_path=str(tmp_path / "gone.pdf"),
                source_status="MISSING",
                upload_id=3,
            )
        ],
        simulations=[
            SimulationEntry(
                kind="simulation",
                user_id=4,
                resource_id=7,
                session_id=7,
                created_at=NOW,
                archive_path="simulations/u00004__simsession_3__lesson__s7.jsonl",
                persona_names={},
                upload_id=3,
            )
        ],
        simulation_utterances={7: [utter]},
        simulation_reports=[
            SimulationReportEntry(
                kind="simulation_report",
                user_id=4,
                resource_id=7,
                session_id=7,
                created_at=NOW,
                archive_path="simulations/u00004__simsession_3__lesson__s7.md",
                markdown="# 세션 7\n",
                upload_id=3,
            )
        ],
        filters=filters,
    )


def _zip(plan) -> zipfile.ZipFile:
    svc = AdminExportService(db=None)
    return zipfile.ZipFile(io.BytesIO(b"".join(svc.stream_zip(plan))))


def _manifest(zf) -> dict[str, dict]:
    rows = csv.DictReader(io.StringIO(zf.read("manifest.csv").decode()))
    return {r["archive_path"]: r for r in rows}


def test_manifest_records_real_size_and_sha(tmp_path):
    zf = _zip(_plan(tmp_path))
    rows = _manifest(zf)

    for path in (
        "reports/u00004__report_3__lesson.md",
        "simulations/u00004__simsession_3__lesson__s7.jsonl",
        "simulations/u00004__simsession_3__lesson__s7.md",
    ):
        data = zf.read(path)
        assert data
        assert rows[path]["byte_size"] == str(len(data))
        assert rows[path]["sha256"] == hashlib.sha256(data).hexdigest()


def test_manifest_written_last(tmp_path):
    zf = _zip(_plan(tmp_path))
    assert zf.namelist()[-1] == "manifest.csv"


def test_manifest_missing_file_has_zero_size_and_no_hash(tmp_path):
    rows = _manifest(_zip(_plan(tmp_path)))
    row = rows["lessonplans/u00004__lessonplan_3__lesson.pdf"]
    assert row["source_status"] == "MISSING"
    assert row["byte_size"] == "0"
    assert row["sha256"] == ""


def test_manifest_includes_simulations(tmp_path):
    rows = _manifest(_zip(_plan(tmp_path)))
    row = rows["simulations/u00004__simsession_3__lesson__s7.jsonl"]
    assert row["kind"] == "simulation"
    assert row["session_id"] == "7"


def test_manifest_upload_id_column_shares_lessonplan_number(tmp_path):
    rows = _manifest(_zip(_plan(tmp_path)))
    assert {r["upload_id"] for r in rows.values()} == {"3"}
    assert rows["reports/u00004__report_3__lesson.md"]["resource_id"] == "1"


def test_manifest_blank_digest_for_entries_not_in_zip(tmp_path):
    zf = _zip(_plan(tmp_path, include={"meta"}))
    rows = _manifest(zf)
    row = rows["reports/u00004__report_3__lesson.md"]
    assert "reports/u00004__report_3__lesson.md" not in zf.namelist()
    assert row["byte_size"] == ""
    assert row["sha256"] == ""


def test_readme_counts_simulations(tmp_path):
    text = build_readme(_plan(tmp_path)).decode("utf-8")
    assert "simulations=1" in text


# ---- 보고서 삭제 시 시뮬레이션 원본 보존 ----


@pytest_asyncio.fixture
async def seeded(tmp_path, monkeypatch):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    lp_base = tmp_path / "data" / "lessonplan"
    lp_base.mkdir(parents=True)
    static_dir = tmp_path / "static" / "uploads"
    static_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "app.services.admin_deletion_service.LESSONPLAN_BASE_DIR",
        str(lp_base),
    )
    monkeypatch.setattr(
        "app.services.admin_deletion_service.STATIC_UPLOADS_DIR",
        str(static_dir),
        raising=False,
    )
    async with TestingSessionLocal() as db:
        admin = User(username="adm", nickname="a", is_admin=True)
        user = User(username="t4", nickname="t", is_admin=False)
        db.add_all([admin, user])
        await db.flush()
        ids = {"admin_id": admin.id, "user_id": user.id}
        for name in ("sim.pdf", "plain.pdf"):
            (lp_base / name).write_bytes(b"%PDF-1.4\n")
            upload = LessonPlanUpload(
                user_id=user.id, filename=name, file_hash="h" + name
            )
            db.add(upload)
            await db.flush()
            report = AnalysisReport(
                user_id=user.id,
                lessonplan_filename=name,
                lessonplan_original_name=name,
                report_filename=name + ".md",
                report_path=str(tmp_path / (name + ".md")),
                upload_id=upload.id,
                latency_ms=1,
            )
            db.add(report)
            await db.flush()
            ids[name] = report.id
            if name == "sim.pdf":
                db.add(
                    SimulationSession(
                        user_id=user.id,
                        upload_id=upload.id,
                        persona_count=1,
                        model_name="m",
                    )
                )
        await db.commit()
    yield ids, lp_base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_report_delete_keeps_lessonplan_used_by_simulation(seeded):
    ids, lp_base = seeded
    async with TestingSessionLocal() as db:
        await AdminDeletionService(db).delete_analysis_report(
            report_id=ids["sim.pdf"], current_admin_id=ids["admin_id"]
        )
    assert (lp_base / "sim.pdf").exists()


@pytest.mark.asyncio
async def test_bulk_report_delete_still_removes_unused_lessonplan(seeded):
    ids, lp_base = seeded
    async with TestingSessionLocal() as db:
        await AdminDeletionService(db).bulk_delete_reports(
            user_id=ids["user_id"],
            report_ids=[ids["sim.pdf"], ids["plain.pdf"]],
            current_admin_id=ids["admin_id"],
        )
    assert (lp_base / "sim.pdf").exists()
    assert not (lp_base / "plain.pdf").exists()


async def _seed_other_user_simulation(name: str) -> None:
    """다른 사용자가 보고서 없이 시뮬레이션으로만 공용 파일을 참조."""
    async with TestingSessionLocal() as db:
        other = User(username="t5", nickname="o", is_admin=False)
        db.add(other)
        await db.flush()
        upload = LessonPlanUpload(
            user_id=other.id, filename=name, file_hash="o" + name
        )
        db.add(upload)
        await db.flush()
        db.add(
            SimulationSession(
                user_id=other.id,
                upload_id=upload.id,
                persona_count=1,
                model_name="m",
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_report_delete_keeps_shared_file_for_other_sim(
    seeded,
):
    ids, lp_base = seeded
    await _seed_other_user_simulation("plain.pdf")
    async with TestingSessionLocal() as db:
        await AdminDeletionService(db).delete_analysis_report(
            report_id=ids["plain.pdf"], current_admin_id=ids["admin_id"]
        )
    assert (lp_base / "plain.pdf").exists()


@pytest.mark.asyncio
async def test_bulk_delete_keeps_shared_file_for_other_sim(
    seeded,
):
    ids, lp_base = seeded
    await _seed_other_user_simulation("plain.pdf")
    async with TestingSessionLocal() as db:
        await AdminDeletionService(db).bulk_delete_reports(
            user_id=ids["user_id"],
            report_ids=[ids["sim.pdf"], ids["plain.pdf"]],
            current_admin_id=ids["admin_id"],
        )
    assert (lp_base / "plain.pdf").exists()
