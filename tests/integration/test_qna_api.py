"""
QnA API 통합 테스트
실제 API 엔드포인트 호출 및 응답 검증
"""
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.users import User
from app.models.documents import Document
from app.models.prompts import SystemPrompt


# 테스트용 임시 파일 DB 설정
import tempfile
import os

# 임시 DB 파일 생성
test_db_fd, test_db_path = tempfile.mkstemp(suffix=".db")
SQLALCHEMY_TEST_DATABASE_URL = f"sqlite+aiosqlite:///{test_db_path}"

engine = create_async_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False
)
TestingSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_db():
    """테스트용 async DB 세션 오버라이드"""
    async with TestingSessionLocal() as database:
        yield database


@pytest_asyncio.fixture(scope="function")
async def setup_test_db():
    """DB 초기화"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
def test_client(setup_test_db):
    """TestClient fixture"""
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app=app, base_url="http://testserver")
    yield client
    app.dependency_overrides.clear()


async def create_test_data():
    """테스트 데이터 생성 헬퍼"""
    async with TestingSessionLocal() as db:
        # 테스트 사용자 생성
        test_user = User(
            username="test_user",
            nickname="Test User",
            hashed_password="hashed_pw",
            is_admin=False
        )
        db.add(test_user)
        await db.commit()
        await db.refresh(test_user)

        # 테스트 문서 생성
        test_doc = Document(
            title="Test Document",
            random_key="test-random-key-123",
            file_path="/test/path.pdf",
            file_size=1024,
            store_id="fileSearchStores/test-store",
            file_search_file_id="file-123",
            user_id=test_user.id,
            status="ready"
        )
        db.add(test_doc)
        await db.commit()
        await db.refresh(test_doc)

        # 테스트 시스템 프롬프트 생성
        test_prompt = SystemPrompt(
            type="qna",
            version=1,
            content="You are a helpful QnA assistant.",
            is_active=True,
            created_by=test_user.id
        )
        db.add(test_prompt)
        await db.commit()

        return test_user.id, test_doc.id


class TestQnAAPI:
    """QnA API 통합 테스트 클래스"""

    def test_qna_endpoint_success(self, test_client):
        """QnA API 정상 호출 테스트"""
        # 테스트 데이터 생성
        import asyncio
        test_user_id, test_doc_id = asyncio.run(create_test_data())

        # Mock Gemini API 응답
        mock_response = Mock()
        mock_response.text = "This is a test answer with citations."
        mock_response.candidates = [Mock()]

        # MockGroundingMetadata 생성
        class MockGroundingChunk:
            def __init__(self, text="Test chunk"):
                self.retrieved_context = Mock()
                self.retrieved_context.text = text

        class MockGroundingMetadata:
            def __init__(self, num_chunks=3):
                self.grounding_chunks = [
                    MockGroundingChunk(f"Chunk {i}")
                    for i in range(num_chunks)
                ]

        mock_response.candidates[0].grounding_metadata = MockGroundingMetadata(3)

        with patch('app.services.qna_service.genai.Client') as mock_client_class:
            mock_client = Mock()
            mock_client.models.generate_content.return_value = mock_response
            mock_client_class.return_value = mock_client

            # 로그인
            login_response = test_client.post(
                "/auth/login",
                data={"username": "test_user", "nickname": "Test User"},
                follow_redirects=False
            )
            assert login_response.status_code == 302

            # QnA 요청
            qna_response = test_client.post(
                f"/qna/{test_doc_id}",
                json={"question": "What is this document about?"}
            )

            assert qna_response.status_code == 200
            result = qna_response.json()

            # 응답 검증
            assert result["question"] == "What is this document about?"
            assert result["answer"] == "This is a test answer with citations."
            assert result["latency_ms"] > 0
            assert result["citations"] is not None
            assert result["grounding_metadata"]["search_performed"] is True
            assert result["grounding_metadata"]["sources_count"] == 3

    def test_qna_endpoint_no_citations(self, test_client):
        """Citations 없는 응답 테스트"""
        # Mock Gemini API 응답 (Citations 없음)
        mock_response = Mock()
        mock_response.text = "I don't have access to the document."
        mock_response.candidates = []

        with patch('app.services.qna_service.genai.Client') as mock_client_class:
            mock_client = Mock()
            mock_client.models.generate_content.return_value = mock_response
            mock_client_class.return_value = mock_client

            # 로그인
            test_client.post(
                "/auth/login",
                data={"username": "test_user", "nickname": "Test User"},
                follow_redirects=False
            )

            # QnA 요청
            qna_response = test_client.post(
                f"/qna/{self.test_doc_id}",
                json={"question": "What is this document about?"}
            )

            assert qna_response.status_code == 200
            result = qna_response.json()

            # 응답 검증
            assert result["citations"] is None
            assert result["grounding_metadata"]["search_performed"] is False
            assert result["grounding_metadata"]["sources_count"] == 0

    def test_qna_endpoint_unauthorized(self, test_client):
        """인증 없이 QnA 요청 시 401 에러"""
        qna_response = test_client.post(
            f"/qna/{self.test_doc_id}",
            json={"question": "Test question"}
        )

        assert qna_response.status_code == 401

    def test_qna_endpoint_invalid_document(self, test_client):
        """존재하지 않는 문서 ID로 요청 시 404 에러"""
        # 로그인
        test_client.post(
            "/auth/login",
            data={"username": "test_user", "nickname": "Test User"},
            follow_redirects=False
        )

        # 존재하지 않는 문서로 QnA 요청
        qna_response = test_client.post(
            "/qna/999999",
            json={"question": "Test question"}
        )

        assert qna_response.status_code == 404

    def test_qna_endpoint_invalid_question(self, test_client):
        """잘못된 질문 형식으로 요청 시 422 에러"""
        # 로그인
        test_client.post(
            "/auth/login",
            data={"username": "test_user", "nickname": "Test User"},
            follow_redirects=False
        )

        # 빈 질문으로 QnA 요청
        qna_response = test_client.post(
            f"/qna/{self.test_doc_id}",
            json={"question": ""}
        )

        assert qna_response.status_code == 422

    def test_qna_endpoint_api_error(self, test_client):
        """Gemini API 에러 시 500 에러"""
        with patch('app.services.qna_service.genai.Client') as mock_client_class:
            mock_client = Mock()
            mock_client.models.generate_content.side_effect = Exception("API Error")
            mock_client_class.return_value = mock_client

            # 로그인
            test_client.post(
                "/auth/login",
                data={"username": "test_user", "nickname": "Test User"},
                follow_redirects=False
            )

            # QnA 요청
            qna_response = test_client.post(
                f"/qna/{self.test_doc_id}",
                json={"question": "Test question"}
            )

            assert qna_response.status_code == 500

    def test_qna_history_endpoint(self, test_client):
        """QnA 히스토리 조회 테스트"""
        # Mock Gemini API 응답
        mock_response = Mock()
        mock_response.text = "Test answer"
        mock_response.candidates = []

        with patch('app.services.qna_service.genai.Client') as mock_client_class:
            mock_client = Mock()
            mock_client.models.generate_content.return_value = mock_response
            mock_client_class.return_value = mock_client

            # 로그인
            test_client.post(
                "/auth/login",
                data={"username": "test_user", "nickname": "Test User"},
                follow_redirects=False
            )

            # QnA 요청 (히스토리 생성)
            test_client.post(
                f"/qna/{self.test_doc_id}",
                json={"question": "Question 1"}
            )
            test_client.post(
                f"/qna/{self.test_doc_id}",
                json={"question": "Question 2"}
            )

            # 히스토리 조회
            history_response = test_client.get(f"/qna/{self.test_doc_id}/history")

            assert history_response.status_code == 200
            history = history_response.json()

            # 히스토리 검증
            assert isinstance(history, list)
            assert len(history) >= 2
            assert all("question" in item for item in history)
            assert all("answer" in item for item in history)

    def test_qna_endpoint_with_conversation_history(self, test_client):
        """대화 히스토리 포함 QnA 요청 테스트"""
        # Mock Gemini API 응답
        mock_response = Mock()
        mock_response.text = "Follow-up answer"
        mock_response.candidates = []

        with patch('app.services.qna_service.genai.Client') as mock_client_class:
            mock_client = Mock()
            mock_client.models.generate_content.return_value = mock_response
            mock_client_class.return_value = mock_client

            # 로그인
            test_client.post(
                "/auth/login",
                data={"username": "test_user", "nickname": "Test User"},
                follow_redirects=False
            )

            # 대화 히스토리 포함 QnA 요청
            qna_response = test_client.post(
                f"/qna/{self.test_doc_id}",
                json={
                    "question": "Follow-up question",
                    "conversation_history": [
                        {"question": "Q1", "answer": "A1"},
                        {"question": "Q2", "answer": "A2"}
                    ]
                }
            )

            assert qna_response.status_code == 200
            result = qna_response.json()
            assert result["answer"] == "Follow-up answer"
