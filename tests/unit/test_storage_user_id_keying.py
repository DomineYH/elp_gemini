"""Tests for per-user storage re-keyed by User.id (issue #91 §0).

Every storage service must use ``user_id: int`` subdirectories instead of
``f"{username}_"`` flat-file prefixes.  Ownership is implicit: a caller can
only reach its own ``{user_id}/`` subtree.
"""
from pathlib import Path

from app.services.lessonplan_storage_service import LessonPlanStorageService
from app.services.analysis_storage_service import AnalysisStorageService
from app.services.report_storage_service import ReportStorageService


# ── LessonPlanStorageService ─────────────────────────────────────────


def test_lessonplan_saved_under_user_id_subdir(tmp_path):
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    res = svc.save_lessonplan(
        user_id=42, original_filename="plan.pdf", file_content=b"x"
    )
    assert Path(res["file_path"]) == tmp_path / "42" / "plan.pdf"
    assert svc.list_lessonplans(user_id=42)[0]["original_filename"] == "plan.pdf"


def test_user_cannot_see_other_users_files(tmp_path):
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    svc.save_lessonplan(user_id=1, original_filename="a.pdf", file_content=b"a")
    svc.save_lessonplan(user_id=12, original_filename="b.pdf", file_content=b"b")
    assert [p["original_filename"] for p in svc.list_lessonplans(user_id=1)] == [
        "a.pdf"
    ]
    assert svc.list_lessonplans(user_id=12)[0]["original_filename"] == "b.pdf"


def test_lessonplan_get_path_uses_subdir(tmp_path):
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    svc.save_lessonplan(user_id=7, original_filename="x.pdf", file_content=b"x")
    result = svc.get_lessonplan_path(user_id=7, original_filename="x.pdf")
    assert result is not None
    assert Path(result) == tmp_path / "7" / "x.pdf"


def test_lessonplan_delete_uses_subdir(tmp_path):
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    svc.save_lessonplan(user_id=5, original_filename="d.pdf", file_content=b"d")
    assert svc.delete_lessonplan(user_id=5, original_filename="d.pdf") is True
    assert svc.list_lessonplans(user_id=5) == []


def test_lessonplan_list_returns_empty_for_missing_user(tmp_path):
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    assert svc.list_lessonplans(user_id=999) == []


def test_lessonplan_overwrite_same_name(tmp_path):
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    svc.save_lessonplan(user_id=3, original_filename="f.pdf", file_content=b"v1")
    svc.save_lessonplan(user_id=3, original_filename="f.pdf", file_content=b"v2")
    files = svc.list_lessonplans(user_id=3)
    assert len(files) == 1
    assert Path(files[0]["file_path"]).read_bytes() == b"v2"


# ── AnalysisStorageService ───────────────────────────────────────────


def test_analysis_saved_under_user_id_subdir(tmp_path):
    svc = AnalysisStorageService(base_dir=str(tmp_path))
    res = svc.save_analysis(
        user_id=10,
        lessonplan_filename="lesson.pdf",
        analysis_content="content",
    )
    assert Path(res["file_path"]).parent == tmp_path / "10"


def test_analysis_list_scoped_to_user(tmp_path):
    svc = AnalysisStorageService(base_dir=str(tmp_path))
    svc.save_analysis(user_id=1, lessonplan_filename="a.pdf", analysis_content="c1")
    svc.save_analysis(user_id=2, lessonplan_filename="b.pdf", analysis_content="c2")
    assert len(svc.list_analyses(user_id=1)) == 1
    assert len(svc.list_analyses(user_id=2)) == 1
    assert svc.list_analyses(user_id=1)[0]["lessonplan_filename"] == "a"


def test_analysis_get_and_delete(tmp_path):
    svc = AnalysisStorageService(base_dir=str(tmp_path))
    svc.save_analysis(user_id=5, lessonplan_filename="x.pdf", analysis_content="hello")
    assert svc.get_analysis(user_id=5, lessonplan_filename="x.pdf") is not None
    assert svc.delete_analysis(user_id=5, lessonplan_filename="x.pdf") is True
    assert svc.get_analysis(user_id=5, lessonplan_filename="x.pdf") is None


def test_analysis_list_empty_for_missing_user(tmp_path):
    svc = AnalysisStorageService(base_dir=str(tmp_path))
    assert svc.list_analyses(user_id=999) == []


# ── ReportStorageService ─────────────────────────────────────────────


def test_report_saved_under_user_id_subdir(tmp_path):
    svc = ReportStorageService(base_dir=str(tmp_path))
    res = svc.save_report(
        user_id=42, original_filename="plan.pdf", report_content="# Report"
    )
    assert Path(res["file_path"]).parent == tmp_path / "42"


def test_report_list_scoped_to_user(tmp_path):
    svc = ReportStorageService(base_dir=str(tmp_path))
    svc.save_report(user_id=1, original_filename="a.pdf", report_content="r1")
    svc.save_report(user_id=2, original_filename="b.pdf", report_content="r2")
    assert len(svc.list_reports(user_id=1)) == 1
    assert len(svc.list_reports(user_id=2)) == 1


def test_report_get_and_delete(tmp_path):
    svc = ReportStorageService(base_dir=str(tmp_path))
    res = svc.save_report(
        user_id=7, original_filename="x.pdf", report_content="hello"
    )
    filename = res["filename"]
    assert svc.get_report_path(user_id=7, filename=filename) is not None
    assert svc.delete_report(user_id=7, filename=filename) is True
    assert svc.get_report_path(user_id=7, filename=filename) is None


def test_report_cannot_access_other_users_file(tmp_path):
    svc = ReportStorageService(base_dir=str(tmp_path))
    res = svc.save_report(
        user_id=1, original_filename="secret.pdf", report_content="mine"
    )
    filename = res["filename"]
    # User 2 must not see user 1's report
    assert svc.get_report_path(user_id=2, filename=filename) is None
    assert svc.delete_report(user_id=2, filename=filename) is False


def test_report_list_empty_for_missing_user(tmp_path):
    svc = ReportStorageService(base_dir=str(tmp_path))
    assert svc.list_reports(user_id=999) == []


def test_report_no_collision_between_same_original_name(tmp_path):
    svc = ReportStorageService(base_dir=str(tmp_path))
    r1 = svc.save_report(user_id=1, original_filename="a.pdf", report_content="u1")
    r2 = svc.save_report(user_id=2, original_filename="a.pdf", report_content="u2")
    # Both files exist independently
    assert Path(r1["file_path"]).exists()
    assert Path(r2["file_path"]).exists()
    assert r1["file_path"] != r2["file_path"]


# ── Path traversal protection ──────────────────────────────────────


def test_lessonplan_traversal_stays_under_user_dir(tmp_path):
    """A filename like '../other_user/x.pdf' must be normalized to stay
    inside the user's own subdirectory."""
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    res = svc.save_lessonplan(
        user_id=5, original_filename="../evil.pdf", file_content=b"x"
    )
    saved = Path(res["file_path"])
    # Must resolve to tmp_path/5/evil.pdf, NOT escape the user dir
    assert saved == tmp_path / "5" / "evil.pdf"
    assert saved.exists()

    # get and delete also work with the traversal-safe name
    assert svc.get_lessonplan_path(user_id=5, original_filename="../evil.pdf") is not None
    assert svc.delete_lessonplan(user_id=5, original_filename="../evil.pdf") is True
