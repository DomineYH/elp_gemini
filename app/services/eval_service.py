"""
문서 평가 서비스 (리팩토링)
파일 기반 평가 결과 저장 및 Vector DB 검색
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from google import genai
from google.genai import types

from app.config import settings
from app.services.analysis_storage_service import (
    AnalysisStorageService
)
from app.services.criteria_vector_service import (
    CriteriaVectorService
)
from app.services.prompt_loader_service import (
    PromptLoaderService
)
from app.services.eval_prompt_builder import (
    EvaluationPromptBuilder
)

logger = logging.getLogger(__name__)


class EvaluationService:
    """문서 평가 서비스 클래스 (파일 기반)"""

    def __init__(self):
        """서비스 초기화"""
        self.analysis_storage = AnalysisStorageService()
        self.criteria_vector = CriteriaVectorService()
        self.prompt_loader = PromptLoaderService()
        self.prompt_builder = EvaluationPromptBuilder()
        self.eval_model_name = settings.GEMINI_EVAL_MODEL
        self.client = genai.Client(
            api_key=settings.GOOGLE_API_KEY
        )

    async def run_evaluation(
        self,
        username: str,
        lessonplan_filename: str,
        user_id: int,
        evaluation_type: str = "general",
    ) -> Dict[str, Any]:
        """
        문서 평가 실행 (파일 기반)

        Args:
            username: 사용자 이름
            lessonplan_filename: 지도안 파일명
            user_id: 사용자 ID
            evaluation_type: 평가 유형

        Returns:
            평가 결과 딕셔너리
            - overall_score: 전체 점수
            - criteria_scores: 기준별 점수
            - feedback: 피드백
            - improvement_suggestions: 개선 제안
            - file_path: 저장된 파일 경로

        Raises:
            ValueError: 평가 기준이 없을 때
        """
        start_time = datetime.now()

        try:
            # 평가 프롬프트 로드
            eval_prompt = self.prompt_loader.get_prompt(
                "evaluation"
            )
            if not eval_prompt:
                raise ValueError(
                    "평가 프롬프트를 찾을 수 없습니다"
                )

            # 평가기준 검색
            try:
                criteria_result = (
                    await self.criteria_vector.search_criteria(
                        query=lessonplan_filename,
                        model=self.eval_model_name,
                        temperature=0.3,
                    )
                )

                if criteria_result['sources_count'] == 0:
                    raise ValueError(
                        "활성화된 평가 기준이 없습니다. "
                        "관리자에게 문의하세요."
                    )

                logger.info(
                    f"평가 기준 검색 완료: "
                    f"{criteria_result['sources_count']}개"
                )

            except ValueError as e:
                logger.error(f"평가 기준 검색 실패: {str(e)}")
                raise

            # 평가 프롬프트 구성
            evaluation_prompt = (
                self.prompt_builder.build_evaluation_prompt(
                    document_title=lessonplan_filename,
                    rubric_content="",
                    system_prompt=eval_prompt,
                    criteria_contexts=[criteria_result],
                )
            )

            # Gemini API로 평가 실행
            report_data = await self._execute_evaluation(
                evaluation_prompt
            )

            # 평가 보고서 마크다운 생성
            markdown_content = self._generate_markdown_report(
                report_data
            )

            # 분석 결과 저장
            save_result = self.analysis_storage.save_analysis(
                username=username,
                lessonplan_filename=lessonplan_filename,
                analysis_content=markdown_content,
                evaluation_type=evaluation_type,
            )

            elapsed_ms = int(
                (datetime.now() - start_time).total_seconds()
                * 1000
            )

            logger.info(
                f"평가 완료: {lessonplan_filename}, "
                f"elapsed={elapsed_ms}ms"
            )

            return {
                **report_data,
                "file_path": save_result["file_path"],
                "filename": save_result["filename"],
                "elapsed_ms": elapsed_ms,
            }

        except ValueError as ve:
            logger.error(f"평가 실행 실패 (기준 없음): {str(ve)}")
            raise

        except Exception as e:
            logger.error(f"평가 실행 실패: {str(e)}")
            raise

    async def _execute_evaluation(
        self, prompt: str
    ) -> Dict[str, Any]:
        """
        Gemini API로 평가 실행

        Args:
            prompt: 평가 프롬프트

        Returns:
            파싱된 평가 결과
        """
        try:
            # API 호출
            response = self.client.models.generate_content(
                model=self.eval_model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3  # 평가는 일관성 중요
                ),
            )

            # 응답 파싱
            return (
                self.prompt_builder.parse_evaluation_response(
                    response.text
                )
            )

        except Exception as e:
            logger.error(f"Gemini API 호출 실패: {str(e)}")
            raise

    def _generate_markdown_report(
        self, report_data: Dict[str, Any]
    ) -> str:
        """
        평가 결과를 마크다운 형식으로 변환

        Args:
            report_data: 평가 결과 데이터

        Returns:
            마크다운 형식의 보고서
        """
        overall_score = report_data.get("overall_score", "N/A")
        criteria_scores = report_data.get("criteria_scores", {})
        feedback = report_data.get("feedback", "")
        suggestions = report_data.get(
            "improvement_suggestions", []
        )

        markdown = f"""## 평가 결과

### 전체 점수
**{overall_score}점**

### 기준별 점수
"""

        # 기준별 점수 추가
        if isinstance(criteria_scores, dict):
            for criterion, score in criteria_scores.items():
                markdown += f"- **{criterion}**: {score}점\n"
        else:
            markdown += "- 기준별 점수 정보 없음\n"

        markdown += f"""
### 종합 피드백
{feedback}

### 개선 제안
"""

        # 개선 제안 추가
        if isinstance(suggestions, list) and suggestions:
            for i, suggestion in enumerate(suggestions, 1):
                markdown += f"{i}. {suggestion}\n"
        else:
            markdown += "- 개선 제안 정보 없음\n"

        return markdown

    def get_analysis(
        self, username: str, lessonplan_filename: str
    ) -> Dict[str, Any]:
        """
        저장된 분석 결과 조회

        Args:
            username: 사용자 이름
            lessonplan_filename: 지도안 파일명

        Returns:
            분석 결과 딕셔너리
            - content: 분석 내용
            - file_path: 파일 경로
        """
        return self.analysis_storage.get_analysis(
            username=username,
            lessonplan_filename=lessonplan_filename,
        )

    def list_analyses(
        self, username: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        분석 결과 목록 조회

        Args:
            username: 사용자 이름 (선택)

        Returns:
            분석 결과 목록
        """
        return self.analysis_storage.list_analyses(
            username=username
        )

    def delete_analysis(
        self, username: str, lessonplan_filename: str
    ) -> bool:
        """
        분석 결과 삭제

        Args:
            username: 사용자 이름
            lessonplan_filename: 지도안 파일명

        Returns:
            삭제 성공 여부
        """
        return self.analysis_storage.delete_analysis(
            username=username,
            lessonplan_filename=lessonplan_filename,
        )
