"""
AnalysisStorageService 단위 테스트
"""
import os
import pytest
import tempfile
import shutil
from pathlib import Path
from app.services.analysis_storage_service import (
    AnalysisStorageService,
)


@pytest.fixture
def temp_storage_dir():
    """테스트용 임시 디렉토리 생성"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def service(temp_storage_dir):
    """AnalysisStorageService 인스턴스 생성"""
    return AnalysisStorageService(base_dir=temp_storage_dir)


def test_save_analysis(service):
    """분석 결과 저장 테스트"""
    # Given
    username = "testuser"
    lessonplan_filename = "lesson1.pdf"
    analysis_content = "## 분석 결과\n\n훌륭한 수업입니다."

    # When
    result = service.save_analysis(
        username, lessonplan_filename, analysis_content
    )

    # Then
    assert "file_path" in result
    assert "filename" in result
    assert "timestamp" in result
    assert result["filename"] == f"{username}_lesson1.md"
    assert Path(result["file_path"]).exists()


def test_markdown_header_generation(service):
    """마크다운 헤더 자동 생성 테스트"""
    # Given
    username = "testuser"
    lessonplan_filename = "lesson1.pdf"
    analysis_content = "분석 내용"

    # When
    result = service.save_analysis(
        username, lessonplan_filename, analysis_content
    )
    content = service.get_analysis(username, lessonplan_filename)

    # Then
    assert "# 수업 지도안 분석 결과" in content
    assert "## 메타데이터" in content
    assert f"**사용자**: {username}" in content
    assert f"**지도안 파일**: {lessonplan_filename}" in content
    assert "**분석 일시**:" in content


def test_get_analysis_exists(service):
    """존재하는 분석 결과 조회 테스트"""
    # Given
    username = "testuser"
    lessonplan_filename = "lesson1.pdf"
    analysis_content = "분석 내용"
    service.save_analysis(
        username, lessonplan_filename, analysis_content
    )

    # When
    content = service.get_analysis(username, lessonplan_filename)

    # Then
    assert content is not None
    assert "분석 내용" in content


def test_get_analysis_not_exists(service):
    """존재하지 않는 분석 결과 조회 테스트"""
    # Given
    username = "testuser"
    lessonplan_filename = "nonexistent.pdf"

    # When
    content = service.get_analysis(username, lessonplan_filename)

    # Then
    assert content is None


def test_list_analyses(service):
    """사용자별 분석 결과 목록 조회 테스트"""
    # Given
    username = "testuser"
    files = [
        ("lesson1.pdf", "분석1"),
        ("lesson2.pdf", "분석2"),
        ("lesson3.pdf", "분석3"),
    ]
    for filename, content in files:
        service.save_analysis(username, filename, content)

    # When
    result = service.list_analyses(username)

    # Then
    assert len(result) == 3
    assert all("filename" in item for item in result)
    assert all(
        "lessonplan_filename" in item for item in result
    )
    assert all("file_path" in item for item in result)
    assert all("size" in item for item in result)
    assert all("created_at" in item for item in result)


def test_list_analyses_empty(service):
    """빈 분석 결과 목록 조회 테스트"""
    # Given
    username = "testuser"

    # When
    result = service.list_analyses(username)

    # Then
    assert len(result) == 0


def test_delete_analysis_exists(service):
    """존재하는 분석 결과 삭제 테스트"""
    # Given
    username = "testuser"
    lessonplan_filename = "lesson1.pdf"
    analysis_content = "분석 내용"
    service.save_analysis(
        username, lessonplan_filename, analysis_content
    )

    # When
    result = service.delete_analysis(
        username, lessonplan_filename
    )

    # Then
    assert result is True
    assert (
        service.get_analysis(username, lessonplan_filename)
        is None
    )


def test_delete_analysis_not_exists(service):
    """존재하지 않는 분석 결과 삭제 테스트"""
    # Given
    username = "testuser"
    lessonplan_filename = "nonexistent.pdf"

    # When
    result = service.delete_analysis(
        username, lessonplan_filename
    )

    # Then
    assert result is False


def test_get_storage_stats(service):
    """저장소 통계 정보 조회 테스트"""
    # Given
    username = "testuser"
    files = [
        ("lesson1.pdf", "분석1"),
        ("lesson2.pdf", "분석2"),
    ]
    for filename, content in files:
        service.save_analysis(username, filename, content)

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
    lessonplan_filename = "my_lesson.pdf"
    analysis_content = "분석 내용"

    # When
    result = service.save_analysis(
        username, lessonplan_filename, analysis_content
    )

    # Then
    # PDF 확장자 제거하고 .md 추가
    expected_filename = f"{username}_my_lesson.md"
    assert result["filename"] == expected_filename


def test_multiple_users(service):
    """여러 사용자 분석 결과 분리 테스트"""
    # Given
    users = ["user1", "user2", "user3"]
    for user in users:
        service.save_analysis(user, "lesson.pdf", "분석")

    # When
    user1_files = service.list_analyses("user1")
    user2_files = service.list_analyses("user2")

    # Then
    assert len(user1_files) == 1
    assert len(user2_files) == 1
    assert user1_files[0]["filename"] == "user1_lesson.md"
    assert user2_files[0]["filename"] == "user2_lesson.md"


def test_evaluation_type_in_header(service):
    """평가 유형이 헤더에 포함되는지 테스트"""
    # Given
    username = "testuser"
    lessonplan_filename = "lesson1.pdf"
    analysis_content = "분석 내용"
    evaluation_type = "comprehensive"

    # When
    service.save_analysis(
        username,
        lessonplan_filename,
        analysis_content,
        evaluation_type,
    )
    content = service.get_analysis(username, lessonplan_filename)

    # Then
    assert f"**평가 유형**: {evaluation_type}" in content


def test_utf8_encoding(service):
    """UTF-8 인코딩 테스트"""
    # Given
    username = "테스트사용자"
    lessonplan_filename = "수업계획.pdf"
    analysis_content = "한글 분석 결과입니다. 🎓"

    # When
    service.save_analysis(
        username, lessonplan_filename, analysis_content
    )
    content = service.get_analysis(username, lessonplan_filename)

    # Then
    assert "한글 분석 결과입니다. 🎓" in content
    assert username in content
