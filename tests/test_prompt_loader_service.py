"""
PromptLoaderService 단위 테스트
"""
import os
import pytest
import tempfile
import shutil
from pathlib import Path
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
    service = PromptLoaderService(
        prompt_file=str(nonexistent_file)
    )

    # Then
    assert len(service.list_available_prompts()) == 0


def test_utf8_encoding(temp_prompt_dir):
    """UTF-8 인코딩 테스트"""
    # Given
    korean_content = """# 프롬프트

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

##

빈 헤더

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
    service = PromptLoaderService(
        prompt_file=real_prompt_file
    )

    # Then
    prompts = service.list_available_prompts()
    assert len(prompts) > 0
    # 최소한 하나의 프롬프트는 존재해야 함
    assert any(
        service.has_prompt(p) for p in ["qna", "evaluation"]
    )
