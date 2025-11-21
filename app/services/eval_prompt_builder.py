"""
평가 프롬프트 구성 및 결과 파싱 유틸리티
"""
import logging
import re
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class EvaluationPromptBuilder:
    """평가 프롬프트 구성 및 파싱 클래스"""

    @staticmethod
    def build_evaluation_prompt(
        document_title: str,
        rubric_content: str,
        system_prompt: str,
        criteria_contexts: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        루브릭 및 평가 기준 기반 평가 프롬프트 구성

        Args:
            document_title: 문서 제목
            rubric_content: 루브릭 내용
            system_prompt: 시스템 프롬프트
            criteria_contexts: 평가 기준 컨텍스트 리스트
                (선택, CriteriaContextService에서 제공)

        Returns:
            완성된 평가 프롬프트
        """
        # 평가 기준 섹션 구성
        criteria_section = ""
        if criteria_contexts:
            criteria_section = (
                "\n\n**참고: 공식 평가 기준**:\n"
            )
            for idx, ctx in enumerate(criteria_contexts, 1):
                content = ctx.get("content", "")
                criteria_section += (
                    f"{idx}. {content}\n\n"
                )

        prompt = f"""
{system_prompt}

아래 문서를 평가해주세요:

**문서 제목**: {document_title}

**평가 기준 (루브릭)**:
{rubric_content}
{criteria_section}
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

    @staticmethod
    def parse_evaluation_response(
        response_text: str,
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
                result["overall_score"] = float(
                    overall_match.group(1)
                )

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
                result["feedback"] = (
                    feedback_match.group(1).strip()
                )
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

            logger.info(
                f"평가 결과 파싱 완료: "
                f"score={result['overall_score']}"
            )
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
