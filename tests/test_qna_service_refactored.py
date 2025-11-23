"""
QnA 서비스 리팩토링 테스트
세션 기반 QnA 동작 검증
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from app.services.qna_service import QnAService
from app.models.chat_sessions import ChatSession
from app.models.chat_messages import ChatMessage, MessageRole


@pytest.fixture
def mock_db():
    """Mock AsyncSession"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.add = Mock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def mock_session():
    """Mock ChatSession"""
    session = Mock(spec=ChatSession)
    session.id = 1
    session.user_id = 100
    session.title = "Test Session"
    return session


@pytest.fixture
def qna_service(mock_db):
    """QnAService 인스턴스"""
    with patch(
        'app.services.qna_service.PromptLoaderService'
    ):
        with patch(
            'app.services.qna_service.FileSearchService'
        ):
            service = QnAService(mock_db)
            return service


class TestQnAServiceRefactored:
    """QnA 서비스 리팩토링 테스트"""

    @pytest.mark.asyncio
    async def test_create_session(
        self, qna_service, mock_db
    ):
        """세션 생성 테스트"""
        user_id = 100
        title = "테스트 세션"

        session = await qna_service.create_session(
            user_id=user_id,
            title=title
        )

        # 세션이 DB에 추가되었는지 확인
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()

        # 세션 속성 확인
        added_session = mock_db.add.call_args[0][0]
        assert isinstance(added_session, ChatSession)
        assert added_session.user_id == user_id
        assert added_session.title == title

    @pytest.mark.asyncio
    async def test_save_messages(
        self, qna_service, mock_db
    ):
        """메시지 저장 테스트"""
        session_id = 1
        question = "테스트 질문"
        answer = "테스트 답변"
        model_name = "gemini-pro"
        citations = {"test": "data"}

        await qna_service._save_messages(
            session_id=session_id,
            question=question,
            answer=answer,
            model_name=model_name,
            citations=citations
        )

        # 2개의 메시지가 추가되었는지 확인 (user, assistant)
        assert mock_db.add.call_count == 2
        mock_db.flush.assert_called_once()

        # 첫 번째 메시지 (user)
        user_msg = mock_db.add.call_args_list[0][0][0]
        assert isinstance(user_msg, ChatMessage)
        assert user_msg.session_id == session_id
        assert user_msg.role == MessageRole.USER
        assert user_msg.content == question

        # 두 번째 메시지 (assistant)
        assistant_msg = mock_db.add.call_args_list[1][0][0]
        assert isinstance(assistant_msg, ChatMessage)
        assert assistant_msg.session_id == session_id
        assert assistant_msg.role == MessageRole.ASSISTANT
        assert assistant_msg.content == answer
        assert assistant_msg.model_name == model_name
        assert assistant_msg.citations == citations

    @pytest.mark.asyncio
    async def test_get_conversation_history(
        self, qna_service, mock_db
    ):
        """대화 히스토리 조회 테스트"""
        session_id = 1

        # Mock 메시지 데이터
        msg1 = Mock(spec=ChatMessage)
        msg1.role = MessageRole.USER
        msg1.content = "질문 1"

        msg2 = Mock(spec=ChatMessage)
        msg2.role = MessageRole.ASSISTANT
        msg2.content = "답변 1"

        msg3 = Mock(spec=ChatMessage)
        msg3.role = MessageRole.USER
        msg3.content = "질문 2"

        msg4 = Mock(spec=ChatMessage)
        msg4.role = MessageRole.ASSISTANT
        msg4.content = "답변 2"

        # DB execute 결과 Mock
        mock_result = AsyncMock()
        mock_result.scalars = Mock(
            return_value=Mock(
                all=Mock(return_value=[msg1, msg2, msg3, msg4])
            )
        )
        mock_db.execute.return_value = mock_result

        # 히스토리 조회
        history = await qna_service.get_conversation_history(
            session_id=session_id,
            limit=10
        )

        # 결과 확인
        assert len(history) == 2
        assert history[0]["question"] == "질문 1"
        assert history[0]["answer"] == "답변 1"
        assert history[1]["question"] == "질문 2"
        assert history[1]["answer"] == "답변 2"

    @pytest.mark.asyncio
    async def test_get_session(
        self, qna_service, mock_db, mock_session
    ):
        """세션 가져오기 테스트"""
        session_id = 1
        user_id = 100

        # DB execute 결과 Mock
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = Mock(
            return_value=mock_session
        )
        mock_db.execute.return_value = mock_result

        # 세션 조회
        session = await qna_service._get_session(
            session_id=session_id,
            user_id=user_id
        )

        # 결과 확인
        assert session == mock_session
        mock_db.execute.assert_called_once()

    def test_extract_citations(self, qna_service):
        """Citation 추출 테스트"""
        # Mock grounding metadata
        mock_metadata = Mock()
        mock_metadata.to_dict = Mock(
            return_value={
                "grounding_chunks": [
                    {"chunk_id": "1"},
                    {"chunk_id": "2"}
                ]
            }
        )

        # Citation 추출
        result = qna_service._extract_citations(mock_metadata)

        # 결과 확인
        assert isinstance(result, dict)
        assert "grounding_chunks" in result
        assert len(result["grounding_chunks"]) == 2

    def test_build_context_without_history(self, qna_service):
        """히스토리 없이 컨텍스트 구성 테스트"""
        system_prompt = "테스트 시스템 프롬프트"

        context = qna_service._build_context(
            system_prompt=system_prompt,
            conversation_history=None
        )

        assert "시스템 프롬프트: 테스트 시스템 프롬프트" in context
        assert "이전 대화:" not in context

    def test_build_context_with_history(self, qna_service):
        """히스토리 포함 컨텍스트 구성 테스트"""
        system_prompt = "테스트 시스템 프롬프트"
        history = [
            {"question": "Q1", "answer": "A1"},
            {"question": "Q2", "answer": "A2"}
        ]

        context = qna_service._build_context(
            system_prompt=system_prompt,
            conversation_history=history
        )

        assert "시스템 프롬프트: 테스트 시스템 프롬프트" in context
        assert "이전 대화:" in context
        assert "Q: Q1" in context
        assert "A: A1" in context
        assert "Q: Q2" in context
        assert "A: A2" in context
