"""
문서 평가 서비스
루브릭 기반 문서 평가 및 보고서 생성 (Criteria 통합)
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.evaluations import (
    EvaluationTemplate,
    EvaluationRun,
    EvaluationReport,
)
from app.models.documents import Document
from app.models.prompts import SystemPrompt
from app.services.criteria_context_service import (
    CriteriaContextService,
)
from app.services.eval_prompt_builder import (
    EvaluationPromptBuilder,
)

logger = logging.getLogger(__name__)


class EvaluationService:
    """문서 평가 서비스 클래스"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.criteria_context = CriteriaContextService()
        self.prompt_builder = EvaluationPromptBuilder()
        self.eval_model_name = settings.GEMINI_EVAL_MODEL
        self.client = genai.Client(
            api_key=settings.GOOGLE_API_KEY
        )

    # NOTE: Criteria 시스템 도입으로 인해
    # 템플릿 업로드 기능은 더 이상 사용되지 않습니다.
    # 기존 코드는 참고용으로 주석 처리합니다.

    async def run_evaluation(
        self,
        document_id: int,
        user_id: int,
        template_id: int,
        prompt_id: int,
    ) -> EvaluationRun:
        """
        문서 평가 실행 (Criteria 기준 통합)

        Args:
            document_id: 평가할 문서 ID
            user_id: 사용자 ID
            template_id: 평가 템플릿 ID
            prompt_id: 시스템 프롬프트 ID

        Returns:
            생성된 EvaluationRun

        Raises:
            ValueError: 활성 평가 기준이 없을 때
        """
        # 평가 실행 레코드 생성
        eval_run = EvaluationRun(
            document_id=document_id,
            user_id=user_id,
            template_id=template_id,
            prompt_id=prompt_id,
            status="pending",
            model_name=self.eval_model_name,
        )
        self.db.add(eval_run)
        await self.db.commit()
        await self.db.refresh(eval_run)

        try:
            # 평가 실행 상태를 running으로 변경
            eval_run.status = "running"
            await self.db.commit()

            # 문서, 템플릿, 프롬프트 가져오기
            document = await self.db.get(Document, document_id)
            template = await self.db.get(
                EvaluationTemplate, template_id
            )
            prompt = await self.db.get(SystemPrompt, prompt_id)

            if not document or not template or not prompt:
                raise ValueError(
                    "문서, 템플릿 또는 프롬프트를 "
                    "찾을 수 없습니다"
                )

            # Criteria 컨텍스트 검색
            try:
                criteria_contexts = (
                    await self.criteria_context.get_context(
                        query=document.title,
                        k=5,
                    )
                )
                logger.info(
                    f"평가 기준 컨텍스트 {len(criteria_contexts)}"
                    f"개 검색 완료"
                )
            except ValueError as e:
                # 활성 기준이 없을 때
                logger.error(
                    f"평가 기준 검색 실패: {str(e)}"
                )
                raise ValueError(
                    "활성화된 평가 기준이 없습니다. "
                    "관리자에게 문의하세요."
                ) from e

            # 평가 프롬프트 구성
            evaluation_prompt = (
                self.prompt_builder.build_evaluation_prompt(
                    document_title=document.title,
                    rubric_content=template.description or "",
                    system_prompt=prompt.content,
                    criteria_contexts=criteria_contexts,
                )
            )

            # Gemini API로 평가 실행
            report_data = await self._execute_evaluation(
                evaluation_prompt
            )

            # 평가 보고서 생성
            report = EvaluationReport(
                run_id=eval_run.id,
                overall_score=report_data.get("overall_score"),
                criteria_scores=report_data.get(
                    "criteria_scores"
                ),
                feedback=report_data.get("feedback", ""),
                improvement_suggestions=report_data.get(
                    "improvement_suggestions"
                ),
            )
            self.db.add(report)

            # 평가 완료 상태로 변경
            eval_run.status = "completed"
            eval_run.completed_at = datetime.now()
            await self.db.commit()

            logger.info(f"평가 완료: run_id={eval_run.id}")
            return eval_run

        except ValueError as ve:
            # 활성 기준 없음 에러 (400 Bad Request)
            logger.error(f"평가 실행 실패 (기준 없음): {str(ve)}")
            eval_run.status = "failed"
            eval_run.error_message = str(ve)
            eval_run.completed_at = datetime.now()
            await self.db.commit()
            raise

        except Exception as e:
            # 일반 에러 (503 Service Unavailable)
            logger.error(f"평가 실행 실패: {str(e)}")
            eval_run.status = "failed"
            eval_run.error_message = str(e)
            eval_run.completed_at = datetime.now()
            await self.db.commit()
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

            # 응답 파싱 (EvaluationPromptBuilder 사용)
            return (
                self.prompt_builder.parse_evaluation_response(
                    response.text
                )
            )

        except Exception as e:
            logger.error(f"Gemini API 호출 실패: {str(e)}")
            raise


    async def get_evaluation_report(
        self, run_id: int
    ) -> Optional[EvaluationReport]:
        """
        평가 보고서 조회

        Args:
            run_id: 평가 실행 ID

        Returns:
            평가 보고서 또는 None
        """
        result = await self.db.execute(
            select(EvaluationReport).where(
                EvaluationReport.run_id == run_id
            )
        )
        return result.scalar_one_or_none()
