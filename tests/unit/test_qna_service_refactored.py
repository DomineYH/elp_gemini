"""
QnAService 리팩토링 테스트
Phase 2에서 리팩토링된 get_dual_store_ids() 사용 검증
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from app.services.qna_service import QnAService
from app.config import settings


class TestQnAServiceRefactored:
    """
    리팩토링된 QnA 서비스 테스트
    get_dual_store_ids() 통합 검증
    """

    @pytest.fixture
    def mock_db(self):
        """Mock AsyncSession"""
        return AsyncMock()

    @pytest.fixture
    def mock_user(self):
        """Mock 사용자"""
        return {
            "id": 42,
            "username": "testuser",
            "email": "test@example.com"
        }

    @pytest.fixture
    def mock_session(self):
        """Mock ChatSession"""
        session = Mock()
        session.id = 1
        session.user_id = 42
        session.title = "Test Session"
        return session

    @pytest.mark.asyncio
    async def test_answer_question_uses_get_dual_store_ids(
        self,
        mock_db,
        mock_user,
        mock_session
    ):
        """
        ask_question()이 get_dual_store_ids() 사용 확인
        """
        with patch('app.services.qna_service.genai.Client'):
            service = QnAService(mock_db)

            # Mock _get_session
            service._get_session = AsyncMock(
                return_value=mock_session
            )

            # Mock prompt_loader
            service.prompt_loader.get_prompt = Mock(
                return_value="QnA System Prompt"
            )

            # Mock get_conversation_history
            service.get_conversation_history = AsyncMock(
                return_value=[]
            )

            # Mock CriteriaContextService
            mock_criteria_service = AsyncMock()
            mock_criteria_service.get_context = AsyncMock(
                return_value={
                    "context_text": "평가기준 컨텍스트",
                    "criteria_ids": [1, 2],
                    "criteria_metadata": []
                }
            )

            with patch(
                'app.services.qna_service.CriteriaContextService',
                return_value=mock_criteria_service
            ):
                # Mock get_dual_store_ids (핵심 테스트)
                service.file_search_service.get_dual_store_ids = Mock(
                    return_value=[
                        "fileSearchStores/rubric",
                        "fileSearchStores/user42"
                    ]
                )

                # Mock Gemini API
                mock_response = Mock()
                mock_response.text = "답변입니다."
                mock_response.candidates = []
                service.client.models.generate_content = Mock(
                    return_value=mock_response
                )

                # Mock _save_messages
                service._save_messages = AsyncMock()

                # When
                result = await service.ask_question(
                    session_id=1,
                    question="테스트 질문",
                    user_id=42
                )

                # Then
                # get_dual_store_ids가 user_id로 호출되었는지 확인
                service.file_search_service.get_dual_store_ids \
                    .assert_called_once_with(
                        user_id=42
                    )

                # 결과 확인
                assert result["answer"] == "답변입니다."
                assert "question" in result
                assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_answer_question_store_error_handling(
        self,
        mock_db,
        mock_user,
        mock_session
    ):
        """
        Store 조회 실패 시 에러 처리
        """
        with patch('app.services.qna_service.genai.Client'):
            service = QnAService(mock_db)

            # Mock _get_session
            service._get_session = AsyncMock(
                return_value=mock_session
            )

            # Mock prompt_loader
            service.prompt_loader.get_prompt = Mock(
                return_value="QnA System Prompt"
            )

            # Mock get_conversation_history
            service.get_conversation_history = AsyncMock(
                return_value=[]
            )

            # Mock CriteriaContextService
            mock_criteria_service = AsyncMock()
            mock_criteria_service.get_context = AsyncMock(
                return_value={
                    "context_text": "",
                    "criteria_ids": [],
                    "criteria_metadata": []
                }
            )

            with patch(
                'app.services.qna_service.CriteriaContextService',
                return_value=mock_criteria_service
            ):
                # Mock get_dual_store_ids - ValueError 발생
                service.file_search_service.get_dual_store_ids = Mock(
                    side_effect=ValueError(
                        "평가기준 스토어(rubricstore)를 "
                        "찾을 수 없습니다"
                    )
                )

                # When & Then
                with pytest.raises(Exception) as exc_info:
                    await service.ask_question(
                        session_id=1,
                        question="테스트 질문",
                        user_id=42
                    )

                # 에러 메시지 확인
                assert "평가기준 스토어" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_answer_question_general_error_handling(
        self,
        mock_db,
        mock_user,
        mock_session
    ):
        """
        일반 예외 발생 시 에러 처리
        """
        with patch('app.services.qna_service.genai.Client'):
            service = QnAService(mock_db)

            # Mock _get_session
            service._get_session = AsyncMock(
                return_value=mock_session
            )

            # Mock prompt_loader
            service.prompt_loader.get_prompt = Mock(
                return_value="QnA System Prompt"
            )

            # Mock get_conversation_history
            service.get_conversation_history = AsyncMock(
                return_value=[]
            )

            # Mock CriteriaContextService
            mock_criteria_service = AsyncMock()
            mock_criteria_service.get_context = AsyncMock(
                return_value={
                    "context_text": "",
                    "criteria_ids": [],
                    "criteria_metadata": []
                }
            )

            with patch(
                'app.services.qna_service.CriteriaContextService',
                return_value=mock_criteria_service
            ):
                # Mock get_dual_store_ids - 일반 Exception 발생
                service.file_search_service.get_dual_store_ids = Mock(
                    side_effect=Exception("예상치 못한 오류")
                )

                # When & Then
                with pytest.raises(Exception):
                    await service.ask_question(
                        session_id=1,
                        question="테스트 질문",
                        user_id=42
                    )
