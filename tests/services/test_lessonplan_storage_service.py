"""LessonPlanStorageService 추가 동작 테스트."""
import hashlib

import pytest

from app.services.lessonplan_storage_service import (
    LessonPlanStorageService,
)


def test_save_lessonplan_returns_file_hash(tmp_path):
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    content = b"hello world"
    result = svc.save_lessonplan(
        username="alice",
        original_filename="plan.pdf",
        file_content=content,
    )
    assert "file_hash" in result
    assert result["file_hash"] == hashlib.sha256(content).hexdigest()
    assert len(result["file_hash"]) == 64


def test_save_lessonplan_different_content_different_hash(tmp_path):
    svc = LessonPlanStorageService(base_dir=str(tmp_path))
    r1 = svc.save_lessonplan(
        username="alice", original_filename="a.pdf",
        file_content=b"aaa",
    )
    r2 = svc.save_lessonplan(
        username="alice", original_filename="b.pdf",
        file_content=b"bbb",
    )
    assert r1["file_hash"] != r2["file_hash"]
