"""
프롬프트 로더 서비스
prompt/prompt.md 파일에서 프롬프트 로드 및 캐싱
"""
import logging
import re
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class PromptLoaderService:
    """프롬프트 로더 서비스"""

    def __init__(self, prompt_file: str = "prompt/prompt.md"):
        """
        서비스 초기화

        Args:
            prompt_file: 프롬프트 마크다운 파일 경로
        """
        self.prompt_file = Path(prompt_file)
        self._cache: Dict[str, str] = {}
        self._load_prompts()

    def _load_prompts(self) -> None:
        """프롬프트 파일 로드 및 캐싱"""
        try:
            if not self.prompt_file.exists():
                logger.warning(
                    f"프롬프트 파일 없음: {self.prompt_file}"
                )
                return

            with open(
                self.prompt_file, "r", encoding="utf-8"
            ) as f:
                content = f.read()

            # 프롬프트 타입별로 추출
            prompts = self._extract_prompt(content)
            self._cache = prompts

            logger.info(
                f"프롬프트 로드 완료: {len(self._cache)}개"
            )
        except Exception as e:
            logger.error(f"프롬프트 로드 실패: {str(e)}")
            raise

    def _extract_prompt(self, content: str) -> Dict[str, str]:
        """
        마크다운에서 프롬프트 추출

        Args:
            content: 마크다운 파일 내용

        Returns:
            프롬프트 타입별 딕셔너리
        """
        prompts = {}

        # ## {prompt_type} 패턴으로 섹션 분리
        sections = re.split(r"\n## ", content)

        for section in sections:
            if not section.strip():
                continue

            # 첫 번째 줄이 프롬프트 타입
            lines = section.split("\n")
            if len(lines) < 2:
                continue

            prompt_type = lines[0].strip()
            prompt_content = "\n".join(lines[1:]).strip()

            # --- 구분선 제거
            prompt_content = prompt_content.split("\n---")[0].strip()

            if prompt_type and prompt_content:
                prompts[prompt_type] = prompt_content
                logger.debug(
                    f"프롬프트 추출: {prompt_type} "
                    f"({len(prompt_content)}자)"
                )

        return prompts

    def get_prompt(
        self, prompt_type: str, default: Optional[str] = None
    ) -> str:
        """
        프롬프트 가져오기 (캐싱)

        Args:
            prompt_type: 프롬프트 타입
                (qna, evaluation, analysis, general)
            default: 기본값 (없으면 빈 문자열)

        Returns:
            프롬프트 내용
        """
        if prompt_type in self._cache:
            logger.debug(
                f"프롬프트 조회 (캐시): {prompt_type}"
            )
            return self._cache[prompt_type]

        logger.warning(
            f"프롬프트 타입 없음: {prompt_type}"
        )
        return default if default is not None else ""

    def reload_cache(self) -> None:
        """캐시 리로드"""
        logger.info("프롬프트 캐시 리로드")
        self._cache.clear()
        self._load_prompts()

    def list_available_prompts(self) -> List[str]:
        """
        사용 가능한 프롬프트 목록

        Returns:
            프롬프트 타입 리스트
        """
        return list(self._cache.keys())

    def has_prompt(self, prompt_type: str) -> bool:
        """
        프롬프트 존재 확인

        Args:
            prompt_type: 프롬프트 타입

        Returns:
            존재 여부
        """
        return prompt_type in self._cache

    def get_prompt_stats(self) -> Dict[str, int]:
        """
        프롬프트 통계 정보

        Returns:
            통계 정보 딕셔너리
            - total_prompts: 전체 프롬프트 개수
            - total_chars: 전체 문자 수
        """
        total_chars = sum(
            len(content) for content in self._cache.values()
        )

        return {
            "total_prompts": len(self._cache),
            "total_chars": total_chars,
        }
