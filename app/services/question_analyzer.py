"""
질문 분석 서비스
질문 유형을 판단하여 메타데이터 필터 적용 여부 결정
"""
import re
from typing import Optional


class QuestionAnalyzer:
    """질문 유형 분석 클래스"""

    # 평가 요청 관련 키워드
    EVALUATION_KEYWORDS = [
        # 직접적인 평가 요청
        "평가",
        "분석",
        "검토",
        "점검",
        "진단",

        # 기준 관련 질문
        "기준",
        "루브릭",
        "채점",

        # 판단 요청
        "어떤가요",
        "어떤가",
        "어떻습니까",
        "적절한가",
        "적합한가",
        "타당한가",
        "괜찮은가",
        "괜찮나",

        # 비교/측정 요청
        "비교",
        "측정",
        "수준",

        # 개선 관련
        "개선",
        "보완",
        "수정",

        # 강점/약점 분석
        "강점",
        "약점",
        "장점",
        "단점",
        "문제점",
    ]

    # 일반 내용 질문 패턴 (평가 아님)
    CONTENT_QUESTION_PATTERNS = [
        r"^(뭐|무엇|어느|어디|언제|누구|왜|어떻게)",  # 5W1H 질문
        r"(주제|목표|내용|방법|활동|자료|평가|시간)",  # 문서 구성 요소 질문
        r"(이|그|저)\s*(문서|지도안|교안|수업)",  # 문서 지칭
    ]

    def __init__(self):
        """QuestionAnalyzer 초기화"""
        pass

    def is_evaluation_request(self, question: str) -> bool:
        """
        질문이 평가 요청인지 판단

        Args:
            question: 사용자 질문

        Returns:
            평가 요청이면 True, 일반 질문이면 False
        """
        if not question:
            return False

        question_lower = question.lower().strip()

        # 1. 평가 키워드가 있으면 평가 요청으로 간주
        for keyword in self.EVALUATION_KEYWORDS:
            if keyword in question_lower:
                return True

        # 2. 일반 내용 질문 패턴이면 평가 요청이 아님
        for pattern in self.CONTENT_QUESTION_PATTERNS:
            if re.search(pattern, question_lower):
                return False

        # 3. 기본값: 일반 질문 (사용자 문서만 검색)
        return False

    def get_filter_strategy(self, question: str) -> Optional[str]:
        """
        질문에 맞는 메타데이터 필터 전략 반환

        Args:
            question: 사용자 질문

        Returns:
            메타데이터 필터 문자열 또는 None
            - None: 두 스토어 모두 검색 (평가 요청)
            - "document_type=\"user_document\"": 사용자 문서만 검색 (일반 질문)
        """
        if self.is_evaluation_request(question):
            # 평가 요청: 두 스토어 모두 검색
            return None
        else:
            # 일반 질문: 사용자 문서만 검색
            return 'document_type="user_document"'

    def analyze_question(self, question: str) -> dict:
        """
        질문 분석 결과를 딕셔너리로 반환

        Args:
            question: 사용자 질문

        Returns:
            {
                "is_evaluation": bool,
                "metadata_filter": str | None,
                "question_type": str  # "evaluation" | "content"
            }
        """
        is_eval = self.is_evaluation_request(question)

        return {
            "is_evaluation": is_eval,
            "metadata_filter": self.get_filter_strategy(question),
            "question_type": "evaluation" if is_eval else "content"
        }
