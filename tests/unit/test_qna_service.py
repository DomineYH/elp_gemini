"""
QnAService 단위 테스트
Citations 추출, 에러 처리, API 통합 검증
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from app.services.qna_service import QnAService
from app.config import settings
from app.models.documents import Document
from app.models.prompts import SystemPrompt


class MockGroundingChunk:
    """GroundingChunk 모킹 클래스"""
    def __init__(self, text="Test chunk"):
        self.retrieved_context = Mock()
        self.retrieved_context.text = text


class MockGroundingMetadata:
    """GroundingMetadata 모킹 클래스"""
    def __init__(self, num_chunks=5):
        self.grounding_chunks = [
            MockGroundingChunk(f"Chunk {i}")
            for i in range(num_chunks)
        ]


class TestQnAService:
    """QnAService 테스트 클래스"""

    @pytest.fixture
    def mock_db(self):
        """Mock AsyncSession"""
        db = AsyncMock()
        return db

    @pytest.fixture
    def mock_document(self):
        """Mock Document"""
        doc = Mock(spec=Document)
        doc.id = 5
        doc.store_id = "fileSearchStores/test-store-123"
        doc.file_search_file_id = "file-123"
        doc.title = "Test Document"
        return doc

    @pytest.fixture
    def mock_prompt(self):
        """Mock SystemPrompt"""
        prompt = Mock(spec=SystemPrompt)
        prompt.id = 1
        prompt.content = "You are a helpful QnA assistant."
        prompt.type = "qna"
        prompt.is_active = True
        return prompt

    @pytest.mark.asyncio
    async def test_init(self, mock_db):
        """QnAService 초기화 테스트"""
        with patch('app.services.qna_service.genai.Client'):
            service = QnAService(mock_db)
            assert service.db == mock_db
            assert service.qna_model_name == settings.GEMINI_QNA_MODEL

    @pytest.mark.asyncio
    async def test_get_active_prompt(self, mock_db, mock_prompt):
        """활성 프롬프트 가져오기 테스트"""
        # Mock DB execute 결과
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_prompt)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch('app.services.qna_service.genai.Client'):
            service = QnAService(mock_db)
            prompt = await service._get_active_prompt("qna")

            assert prompt == mock_prompt
            assert prompt.type == "qna"
            assert prompt.is_active is True

    @pytest.mark.asyncio
    async def test_get_active_prompt_not_found(self, mock_db):
        """활성 프롬프트 없을 때 테스트"""
        # Mock DB execute 결과 - None 반환
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch('app.services.qna_service.genai.Client'):
            service = QnAService(mock_db)
            prompt = await service._get_active_prompt("qna")

            assert prompt is None

    @pytest.mark.asyncio
    async def test_ask_question_success_with_citations(
        self, mock_db, mock_document, mock_prompt
    ):
        """정상적인 QnA 요청 및 Citations 반환 테스트"""
        # Mock DB execute 결과 (프롬프트 조회)
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_prompt)
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Mock Gemini API 응답
        mock_response = Mock()
        mock_response.text = "This is a test answer with citations."
        mock_response.candidates = [Mock()]
        mock_response.candidates[0].grounding_metadata = MockGroundingMetadata(5)

        # Mock Gemini Client
        mock_client = Mock()
        mock_client.models.generate_content.return_value = mock_response

        with patch('app.services.qna_service.genai.Client', return_value=mock_client):
            service = QnAService(mock_db)

            result = await service.ask_question(
                document=mock_document,
                question="What is this document about?",
                user_id=1
            )

            # 결과 검증
            assert result["question"] == "What is this document about?"
            assert result["answer"] == "This is a test answer with citations."
            assert result["latency_ms"] > 0
            assert result["citations"] is not None
            assert result["grounding_metadata"]["search_performed"] is True
            assert result["grounding_metadata"]["sources_count"] == 5

    @pytest.mark.asyncio
    async def test_ask_question_no_citations(
        self, mock_db, mock_document, mock_prompt
    ):
        """Citations 없는 응답 테스트"""
        # Mock DB execute 결과
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_prompt)
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Mock Gemini API 응답 (Citations 없음)
        mock_response = Mock()
        mock_response.text = "I don't have access to the document."
        mock_response.candidates = []

        # Mock Gemini Client
        mock_client = Mock()
        mock_client.models.generate_content.return_value = mock_response

        with patch('app.services.qna_service.genai.Client', return_value=mock_client):
            service = QnAService(mock_db)

            result = await service.ask_question(
                document=mock_document,
                question="What is this document about?",
                user_id=1
            )

            # 결과 검증
            assert result["citations"] is None
            assert result["grounding_metadata"]["search_performed"] is False
            assert result["grounding_metadata"]["sources_count"] == 0

    @pytest.mark.asyncio
    async def test_ask_question_no_active_prompt(
        self, mock_db, mock_document
    ):
        """활성 프롬프트 없을 때 에러 처리 테스트"""
        # Mock DB execute 결과 - None 반환
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch('app.services.qna_service.genai.Client'):
            service = QnAService(mock_db)

            with pytest.raises(ValueError) as exc_info:
                await service.ask_question(
                    document=mock_document,
                    question="Test question",
                    user_id=1
                )

            assert "활성 QnA 프롬프트를 찾을 수 없습니다" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_ask_question_api_error(
        self, mock_db, mock_document, mock_prompt
    ):
        """Gemini API 에러 처리 테스트"""
        # Mock DB execute 결과
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_prompt)
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Mock Gemini Client - API 에러 발생
        mock_client = Mock()
        mock_client.models.generate_content.side_effect = Exception("API Error")

        with patch('app.services.qna_service.genai.Client', return_value=mock_client):
            service = QnAService(mock_db)

            with pytest.raises(Exception) as exc_info:
                await service.ask_question(
                    document=mock_document,
                    question="Test question",
                    user_id=1
                )

            assert "API Error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_build_context_without_history(self, mock_db):
        """대화 히스토리 없는 컨텍스트 구성 테스트"""
        with patch('app.services.qna_service.genai.Client'):
            service = QnAService(mock_db)

            context = service._build_context(
                system_prompt="You are helpful.",
                conversation_history=None
            )

            assert "시스템 프롬프트: You are helpful." in context
            assert "이전 대화:" not in context

    @pytest.mark.asyncio
    async def test_build_context_with_history(self, mock_db):
        """대화 히스토리 포함 컨텍스트 구성 테스트"""
        conversation_history = [
            {"question": "Q1", "answer": "A1"},
            {"question": "Q2", "answer": "A2"},
        ]

        with patch('app.services.qna_service.genai.Client'):
            service = QnAService(mock_db)

            context = service._build_context(
                system_prompt="You are helpful.",
                conversation_history=conversation_history
            )

            assert "시스템 프롬프트: You are helpful." in context
            assert "이전 대화:" in context
            assert "Q: Q1" in context
            assert "A: A1" in context

    @pytest.mark.asyncio
    async def test_save_qa_log(self, mock_db):
        """QA 로그 저장 테스트"""
        with patch('app.services.qna_service.genai.Client'):
            service = QnAService(mock_db)

            await service._save_qa_log(
                document_id=5,
                user_id=1,
                prompt_id=1,
                question="Test question",
                answer="Test answer",
                model_name="gemini-2.5-flash",
                latency_ms=1000,
                citations={"test": "data"},
                sources_count=3
            )

            # DB add와 flush가 호출되었는지 확인
            assert mock_db.add.called
            assert mock_db.flush.called

    @pytest.mark.asyncio
    async def test_get_qa_history(self, mock_db):
        """QA 히스토리 조회 테스트"""
        # Mock DB execute 결과
        mock_logs = [Mock(), Mock(), Mock()]
        mock_scalars = Mock()
        mock_scalars.all = Mock(return_value=mock_logs)
        mock_result = Mock()
        mock_result.scalars = Mock(return_value=mock_scalars)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch('app.services.qna_service.genai.Client'):
            service = QnAService(mock_db)

            history = await service.get_qa_history(
                document_id=5,
                user_id=1,
                limit=10
            )

            assert len(history) == 3
            assert mock_db.execute.called

    def test_citations_serialization(self):
        """Citations 직렬화 테스트"""
        # to_serializable 함수가 GroundingMetadata를 올바르게 변환하는지 테스트
        grounding = MockGroundingMetadata(3)

        # 직렬화 함수 (실제 코드에서 사용되는 로직)
        def to_serializable(obj):
            if hasattr(obj, 'to_dict'):
                return obj.to_dict()
            elif hasattr(obj, '__dict__'):
                result = {}
                for key, value in vars(obj).items():
                    if isinstance(value, list):
                        result[key] = [to_serializable(item) for item in value]
                    elif hasattr(value, '__dict__') or hasattr(value, 'to_dict'):
                        result[key] = to_serializable(value)
                    else:
                        result[key] = value
                return result
            else:
                return str(obj)

        citations = to_serializable(grounding)

        # 검증
        assert isinstance(citations, dict)
        assert 'grounding_chunks' in citations
        assert len(citations['grounding_chunks']) == 3

    @pytest.mark.asyncio
    async def test_metadata_filter_removed(
        self, mock_db, mock_document, mock_prompt
    ):
        """메타데이터 필터가 제거되었는지 확인"""
        # Mock DB execute 결과
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_prompt)
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Mock Gemini API 응답
        mock_response = Mock()
        mock_response.text = "Test answer"
        mock_response.candidates = []

        # Mock Gemini Client
        mock_client = Mock()
        mock_client.models.generate_content.return_value = mock_response

        with patch('app.services.qna_service.genai.Client', return_value=mock_client):
            service = QnAService(mock_db)

            await service.ask_question(
                document=mock_document,
                question="Test question",
                user_id=1
            )

            # generate_content 호출 인자 확인
            call_args = mock_client.models.generate_content.call_args
            config = call_args.kwargs['config']

            # FileSearch 설정 확인
            file_search = config.tools[0].file_search
            assert file_search.file_search_store_names == [mock_document.store_id]

            # metadata_filter가 None이거나 없는지 확인
            assert not hasattr(file_search, 'metadata_filter') or \
                   file_search.metadata_filter is None
