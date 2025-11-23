"""
LessonPlanStorageService 단위 테스트
"""
import os
import pytest
import tempfile
import shutil
from pathlib import Path
from app.services.lessonplan_storage_service import (
    LessonPlanStorageService,
)


@pytest.fixture
def temp_storage_dir():
    """테스트용 임시 디렉토리 생성"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def service(temp_storage_dir):
    """LessonPlanStorageService 인스턴스 생성"""
    return LessonPlanStorageService(base_dir=temp_storage_dir)


def test_save_lessonplan(service):
    """지도안 저장 테스트"""
    # Given
    username = "testuser"
    original_filename = "lesson1.pdf"
    file_content = b"test content"

    # When
    result = service.save_lessonplan(
        username, original_filename, file_content
    )

    # Then
    assert "file_path" in result
    assert "filename" in result
    assert "timestamp" in result
    assert result["filename"] == f"{username}_{original_filename}"
    assert Path(result["file_path"]).exists()


def test_get_lessonplan_path_exists(service):
    """존재하는 지도안 경로 조회 테스트"""
    # Given
    username = "testuser"
    original_filename = "lesson1.pdf"
    file_content = b"test content"
    service.save_lessonplan(
        username, original_filename, file_content
    )

    # When
    path = service.get_lessonplan_path(
        username, original_filename
    )

    # Then
    assert path is not None
    assert Path(path).exists()


def test_get_lessonplan_path_not_exists(service):
    """존재하지 않는 지도안 경로 조회 테스트"""
    # Given
    username = "testuser"
    original_filename = "nonexistent.pdf"

    # When
    path = service.get_lessonplan_path(
        username, original_filename
    )

    # Then
    assert path is None


def test_list_lessonplans(service):
    """사용자별 지도안 목록 조회 테스트"""
    # Given
    username = "testuser"
    files = [
        ("lesson1.pdf", b"content1"),
        ("lesson2.pdf", b"content2"),
        ("lesson3.pdf", b"content3"),
    ]
    for filename, content in files:
        service.save_lessonplan(username, filename, content)

    # When
    result = service.list_lessonplans(username)

    # Then
    assert len(result) == 3
    assert all("filename" in item for item in result)
    assert all("original_filename" in item for item in result)
    assert all("file_path" in item for item in result)
    assert all("size" in item for item in result)
    assert all("created_at" in item for item in result)


def test_list_lessonplans_empty(service):
    """빈 지도안 목록 조회 테스트"""
    # Given
    username = "testuser"

    # When
    result = service.list_lessonplans(username)

    # Then
    assert len(result) == 0


def test_delete_lessonplan_exists(service):
    """존재하는 지도안 삭제 테스트"""
    # Given
    username = "testuser"
    original_filename = "lesson1.pdf"
    file_content = b"test content"
    service.save_lessonplan(
        username, original_filename, file_content
    )

    # When
    result = service.delete_lessonplan(
        username, original_filename
    )

    # Then
    assert result is True
    assert (
        service.get_lessonplan_path(username, original_filename)
        is None
    )


def test_delete_lessonplan_not_exists(service):
    """존재하지 않는 지도안 삭제 테스트"""
    # Given
    username = "testuser"
    original_filename = "nonexistent.pdf"

    # When
    result = service.delete_lessonplan(
        username, original_filename
    )

    # Then
    assert result is False


def test_get_storage_stats(service):
    """저장소 통계 정보 조회 테스트"""
    # Given
    username = "testuser"
    files = [
        ("lesson1.pdf", b"content1"),
        ("lesson2.pdf", b"content2"),
    ]
    for filename, content in files:
        service.save_lessonplan(username, filename, content)

    # When
    stats = service.get_storage_stats()

    # Then
    assert "total_files" in stats
    assert "total_size" in stats
    assert stats["total_files"] == 2
    assert stats["total_size"] > 0


def test_filename_format(service):
    """파일명 규칙 검증 테스트"""
    # Given
    username = "testuser"
    original_filename = "my_lesson.pdf"
    file_content = b"test content"

    # When
    result = service.save_lessonplan(
        username, original_filename, file_content
    )

    # Then
    expected_filename = f"{username}_{original_filename}"
    assert result["filename"] == expected_filename


def test_multiple_users(service):
    """여러 사용자 지도안 분리 테스트"""
    # Given
    users = ["user1", "user2", "user3"]
    for user in users:
        service.save_lessonplan(user, "lesson.pdf", b"content")

    # When
    user1_files = service.list_lessonplans("user1")
    user2_files = service.list_lessonplans("user2")

    # Then
    assert len(user1_files) == 1
    assert len(user2_files) == 1
    assert user1_files[0]["filename"] == "user1_lesson.pdf"
    assert user2_files[0]["filename"] == "user2_lesson.pdf"
