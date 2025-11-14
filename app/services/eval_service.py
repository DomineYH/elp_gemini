"""
문서 평가 서비스
루브릭 기반 문서 평가 및 보고서 생성
"""
import logging
import re
import json
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
from app.services.file_search_service import FileSearchService

logger = logging.getLogger(__name__)


class EvaluationService:
    """문서 평가 서비스 클래스"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.file_search = FileSearchService()
        self.eval_model_name = settings.GEMINI_EVAL_MODEL
        self.client = genai.Client(api_key=settings.GOOGLE_API_KEY)

    async def upload_evaluation_template(
        self,
        file_path: str,
        name: str,
        description: Optional[str] = None,
    ) -> EvaluationTemplate:
        """
        평가 템플릿을 rubric 스토어에 업로드

        Args:
            file_path: 템플릿 파일 경로
            name: 템플릿 이름
            description: 템플릿 설명

        Returns:
            생성된 EvaluationTemplate
        """
        try:
            # rubric 스토어에 업로드
            result = await self.file_search.upload_document(
                file_path=file_path,
                display_name=name,
                metadata={"template_name": name},
                store_type="rubric",
            )

            # DB에 템플릿 저장
            template = EvaluationTemplate(
                name=name,
                description=description,
                file_path=file_path,
                file_search_file_id=result["file_id"],
                store_id=result["store_id"],
                is_active=True,
            )
            self.db.add(template)
            await self.db.commit()
            await self.db.refresh(template)

            logger.info(f"평가 템플릿 업로드 완료: {name}")
            return template

        except Exception as e:
            logger.error(f"템플릿 업로드 실패: {str(e)}")
            await self.db.rollback()
            raise

    async def run_evaluation(
        self,
        document_id: int,
        user_id: int,
        template_id: int,
        prompt_id: int,
    ) -> EvaluationRun:
        """
        문서 평가 실행

        Args:
            document_id: 평가할 문서 ID
            user_id: 사용자 ID
            template_id: 평가 템플릿 ID
            prompt_id: 시스템 프롬프트 ID

        Returns:
            생성된 EvaluationRun
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
                raise ValueError("문서, 템플릿 또는 프롬프트를 찾을 수 없습니다")

            # 평가 프롬프트 구성
            evaluation_prompt = self._build_evaluation_prompt(
                document_title=document.title,
                rubric_content=template.description or "",
                system_prompt=prompt.content,
            )

            # Gemini API로 평가 실행
            report_data = await self._execute_evaluation(
                evaluation_prompt
            )

            # 평가 보고서 생성
            report = EvaluationReport(
                run_id=eval_run.id,
                overall_score=report_data.get("overall_score"),
                criteria_scores=report_data.get("criteria_scores"),
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

        except Exception as e:
            logger.error(f"평가 실행 실패: {str(e)}")
            eval_run.status = "failed"
            eval_run.error_message = str(e)
            eval_run.completed_at = datetime.now()
            await self.db.commit()
            raise

    def _build_evaluation_prompt(
        self,
        document_title: str,
        rubric_content: str,
        system_prompt: str,
    ) -> str:
        """
        루브릭 기반 평가 프롬프트 구성

        Args:
            document_title: 문서 제목
            rubric_content: 루브릭 내용
            system_prompt: 시스템 프롬프트

        Returns:
            완성된 평가 프롬프트
        """
        prompt = f"""
{system_prompt}

아래 문서를 평가해주세요:

**문서 제목**: {document_title}

**평가 기준 (루브릭)**:
{rubric_content}

다음 형식으로 평가 결과를 작성해주세요:

## 종합 점수
[0-100 사이의 점수]

## 기준별 점수
- 기준1: [점수]
- 기준2: [점수]
...

## 평가 피드백
[상세한 평가 의견]

## 개선 제안
[구체적인 개선 방안]
"""
        return prompt.strip()

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
                )
            )

            # 응답 파싱
            return self._parse_evaluation_response(response.text)

        except Exception as e:
            logger.error(f"Gemini API 호출 실패: {str(e)}")
            raise

    def _parse_evaluation_response(
        self, response_text: str
    ) -> Dict[str, Any]:
        """
        평가 결과 파싱 및 점수 추출

        Args:
            response_text: Gemini API 응답 텍스트

        Returns:
            파싱된 평가 데이터
        """
        try:
            result = {
                "overall_score": None,
                "criteria_scores": {},
                "feedback": "",
                "improvement_suggestions": None,
            }

            # 종합 점수 추출
            overall_match = re.search(
                r"종합 점수[:\s]*(\d+\.?\d*)", response_text
            )
            if overall_match:
                result["overall_score"] = float(overall_match.group(1))

            # 기준별 점수 추출
            criteria_pattern = r"-\s*(.+?):\s*(\d+\.?\d*)"
            criteria_matches = re.finditer(
                criteria_pattern, response_text
            )
            for match in criteria_matches:
                criterion = match.group(1).strip()
                score = float(match.group(2))
                result["criteria_scores"][criterion] = score

            # 피드백 추출
            feedback_match = re.search(
                r"평가 피드백[:\s]*(.*?)(?=##|$)",
                response_text,
                re.DOTALL,
            )
            if feedback_match:
                result["feedback"] = feedback_match.group(1).strip()
            else:
                result["feedback"] = response_text

            # 개선 제안 추출
            suggestions_match = re.search(
                r"개선 제안[:\s]*(.*?)(?=##|$)",
                response_text,
                re.DOTALL,
            )
            if suggestions_match:
                result["improvement_suggestions"] = (
                    suggestions_match.group(1).strip()
                )

            logger.info(f"평가 결과 파싱 완료: score={result['overall_score']}")
            return result

        except Exception as e:
            logger.error(f"평가 결과 파싱 실패: {str(e)}")
            # 파싱 실패 시 기본값 반환
            return {
                "overall_score": None,
                "criteria_scores": {},
                "feedback": response_text,
                "improvement_suggestions": None,
            }

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
