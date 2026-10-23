"""
PromptLoaderService 단위 테스트
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from app.services.prompt_loader_service import (
    PromptLoaderService,
)


@pytest.fixture
def temp_prompt_dir():
    """테스트용 임시 디렉토리 생성"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_prompt_content():
    """샘플 프롬프트 마크다운 내용"""
    return """# 시스템 프롬프트 템플릿

---

## qna

당신은 질문답변 전문가입니다.

**역할**:
- 정확한 답변 제공
- 근거 기반 응답

---

## evaluation

당신은 평가 전문가입니다.

**역할**:
- 객관적 평가
- 체계적 피드백

---

## general

당신은 유용한 AI입니다.

**역할**:
- 친절한 응답
- 명확한 설명
"""


@pytest.fixture
def temp_prompt_file(temp_prompt_dir, sample_prompt_content):
    """임시 프롬프트 파일 생성"""
    prompt_file = Path(temp_prompt_dir) / "prompt.md"
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(sample_prompt_content)
    return str(prompt_file)


@pytest.fixture
def service(temp_prompt_file):
    """PromptLoaderService 인스턴스 생성"""
    return PromptLoaderService(prompt_file=temp_prompt_file)


def test_load_prompts(service):
    """프롬프트 로드 테스트"""
    # When
    prompts = service.list_available_prompts()

    # Then
    assert len(prompts) == 3
    assert "qna" in prompts
    assert "evaluation" in prompts
    assert "general" in prompts


def test_get_prompt_exists(service):
    """존재하는 프롬프트 조회 테스트"""
    # When
    prompt = service.get_prompt("qna")

    # Then
    assert prompt is not None
    assert "질문답변 전문가" in prompt
    assert "정확한 답변 제공" in prompt


def test_get_prompt_not_exists(service):
    """존재하지 않는 프롬프트 조회 테스트"""
    # When
    prompt = service.get_prompt("nonexistent")

    # Then
    assert prompt == ""


def test_get_prompt_with_default(service):
    """기본값을 가진 프롬프트 조회 테스트"""
    # Given
    default_prompt = "기본 프롬프트"

    # When
    prompt = service.get_prompt("nonexistent", default_prompt)

    # Then
    assert prompt == default_prompt


def test_has_prompt(service):
    """프롬프트 존재 확인 테스트"""
    # Then
    assert service.has_prompt("qna") is True
    assert service.has_prompt("evaluation") is True
    assert service.has_prompt("nonexistent") is False


def test_list_available_prompts(service):
    """사용 가능한 프롬프트 목록 조회 테스트"""
    # When
    prompts = service.list_available_prompts()

    # Then
    assert isinstance(prompts, list)
    assert len(prompts) == 3
    assert all(isinstance(p, str) for p in prompts)


def test_reload_cache(service):
    """캐시 리로드 테스트"""
    # Given
    initial_prompt = service.get_prompt("qna")

    # When
    service.reload_cache()
    reloaded_prompt = service.get_prompt("qna")

    # Then
    assert reloaded_prompt == initial_prompt


def test_get_prompt_stats(service):
    """프롬프트 통계 정보 조회 테스트"""
    # When
    stats = service.get_prompt_stats()

    # Then
    assert "total_prompts" in stats
    assert "total_chars" in stats
    assert stats["total_prompts"] == 3
    assert stats["total_chars"] > 0


def test_extract_prompt_format(service):
    """프롬프트 추출 형식 테스트"""
    # When
    qna_prompt = service.get_prompt("qna")

    # Then
    # --- 구분선이 제거되었는지 확인
    assert "---" not in qna_prompt
    # ## 헤더가 포함되지 않았는지 확인
    assert not qna_prompt.startswith("##")


def test_empty_prompt_file(temp_prompt_dir):
    """빈 프롬프트 파일 처리 테스트"""
    # Given
    empty_file = Path(temp_prompt_dir) / "empty.md"
    empty_file.write_text("", encoding="utf-8")

    # When
    service = PromptLoaderService(prompt_file=str(empty_file))

    # Then
    assert len(service.list_available_prompts()) == 0


def test_nonexistent_prompt_file(temp_prompt_dir):
    """존재하지 않는 프롬프트 파일 처리 테스트"""
    # Given
    nonexistent_file = Path(temp_prompt_dir) / "nonexistent.md"

    # When
    service = PromptLoaderService(prompt_file=str(nonexistent_file))

    # Then
    assert len(service.list_available_prompts()) == 0


def test_utf8_encoding(temp_prompt_dir):
    """UTF-8 인코딩 테스트"""
    # Given
    korean_content = """# 프롬프트

---

## korean

당신은 한국어 전문가입니다. 🇰🇷

**역할**:
- 정확한 한국어 사용
- 자연스러운 표현
"""
    prompt_file = Path(temp_prompt_dir) / "korean.md"
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(korean_content)

    # When
    service = PromptLoaderService(prompt_file=str(prompt_file))
    prompt = service.get_prompt("korean")

    # Then
    assert "한국어 전문가" in prompt
    assert "🇰🇷" in prompt


def test_caching_mechanism(service):
    """캐싱 메커니즘 테스트"""
    # When
    first_call = service.get_prompt("qna")
    second_call = service.get_prompt("qna")

    # Then
    # 같은 객체가 반환되는지 확인 (캐싱)
    assert first_call is second_call


def test_malformed_markdown(temp_prompt_dir):
    """잘못된 형식의 마크다운 처리 테스트"""
    # Given
    malformed_content = """# 프롬프트

---

##

빈 헤더

---

## valid

정상 프롬프트
"""
    prompt_file = Path(temp_prompt_dir) / "malformed.md"
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(malformed_content)

    # When
    service = PromptLoaderService(prompt_file=str(prompt_file))

    # Then
    # 정상적인 프롬프트만 로드되어야 함
    assert service.has_prompt("valid") is True


def test_integration_with_real_file():
    """실제 프롬프트 파일 통합 테스트"""
    # Given
    real_prompt_file = "prompt/prompt.md"

    # 파일이 존재하는 경우에만 테스트 실행
    if not Path(real_prompt_file).exists():
        pytest.skip("실제 프롬프트 파일 없음")

    # When
    service = PromptLoaderService(prompt_file=real_prompt_file)

    # Then
    prompts = service.list_available_prompts()
    assert len(prompts) > 0
    # 최소한 하나의 프롬프트는 존재해야 함
    assert any(service.has_prompt(p) for p in ["qna", "evaluation"])


def test_lesson_analysis_prompt_has_no_leaking_instructions():
    """보고서에 그대로 복사되던 지시문·날짜 자리표시자가 없다 (#172)."""
    prompt = PromptLoaderService().get_prompt("lesson_analysis")

    for leaked in (
        "File Search로 확인한 rubricstore",
        "검색 결과에 없는 기준",
        "File Search 평가기준 요약",
        "[YYYY-MM-DD",
    ):
        assert leaked not in prompt, leaked
    assert "### File Search 참고 문서" in prompt


def _backups(prompt_file: str) -> list:
    path = Path(prompt_file)
    return sorted(path.parent.glob(f"{path.name}.bak-*"))


def test_update_writes_backup_of_previous_content(service, temp_prompt_file):
    """저장 전 이전 내용을 .bak-<ts> 파일로 남긴다 (#268)"""
    before = Path(temp_prompt_file).read_text(encoding="utf-8")

    service.update_prompt("qna", "새 QnA 프롬프트")

    backups = _backups(temp_prompt_file)
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == before


def test_first_save_without_existing_file_creates_no_backup(temp_prompt_dir):
    prompt_file = Path(temp_prompt_dir) / "new.md"
    service = PromptLoaderService(prompt_file=str(prompt_file))

    service.create_prompt("qna", "내용")

    assert prompt_file.exists()
    assert _backups(str(prompt_file)) == []


def test_backups_pruned_to_keep_limit(service, temp_prompt_file):
    service.BACKUP_KEEP = 3
    for i in range(5):
        service.update_prompt("qna", f"내용 {i}")

    backups = _backups(temp_prompt_file)
    assert len(backups) == 3
    # 가장 최근 백업은 마지막 저장 직전 내용(4번째 저장 결과)이다.
    assert "내용 3" in backups[-1].read_text(encoding="utf-8")
