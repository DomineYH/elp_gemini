"""
공통 테스트 픽스처 및 헬퍼 함수
단위 테스트와 통합 테스트에서 공통으로 사용
"""
import os
import pytest
import pytest_asyncio
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker
)
from sqlalchemy.pool import StaticPool
import tempfile
from io import BytesIO

from app.main import app
from app.db import Base, get_db
from app.models.users import User


# ===== 단위 테스트 공통 픽스처 =====


@pytest.fixture
def mock_settings():
    """Mock Settings (단위 테스트용)"""
    with patch(
        "app.services.criteria_embedding_service.settings"
    ) as mock:
        mock.GOOGLE_API_KEY = "test-key"
        mock.FS_CHUNKING_MAX_TOKENS = 1000
        mock.FS_CHUNKING_OVERLAP_TOKENS = 100
        mock.FS_UPLOAD_TIMEOUT = 60
        mock.FS_POLL_INTERVAL = 1
        yield mock


@pytest.fixture
def mock_genai():
    """Mock Google Genai (단위 테스트용)"""
    with patch(
        "app.services.criteria_embedding_service.genai"
    ) as mock:
        yield mock


@pytest.fixture
def mock_genai_client():
    """Mock Google Genai Client (단위 테스트용)"""
    client = MagicMock()
    client.file_search_stores.create.return_value = (
        MagicMock(name="stores/test-store-123")
    )
    client.file_search_stores.delete = MagicMock()
    return client


@pytest.fixture
def mock_store():
    """Mock Vector Store (단위 테스트용)"""
    store = MagicMock()
    store.name = "stores/criteria-1234567890-abcd1234"
    store.display_name = "test-store"
    return store


@pytest.fixture
def mock_operation_complete():
    """완료된 Operation Mock (단위 테스트용)"""
    op = MagicMock()
    op.done = True
    op.name = "operations/test-op-complete"
    op.response.parent = "stores/vector-123"
    op.response.document_name = "docs/test-doc"
    return op


@pytest.fixture
def mock_operation_incomplete():
    """미완료 Operation Mock (단위 테스트용)"""
    op = MagicMock()
    op.done = False
    op.name = "operations/test-op-incomplete"
    return op


# ===== 통합 테스트 공통 픽스처 =====


# 테스트용 임시 DB
test_db_fd, test_db_path = tempfile.mkstemp(suffix=".db")
os.close(test_db_fd)  # FD 누수 방지
SQLALCHEMY_TEST_DATABASE_URL = (
    f"sqlite+aiosqlite:///{test_db_path}"
)

engine = create_async_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False
)
TestingSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def override_get_db():
    """테스트용 DB 세션"""
    async with TestingSessionLocal() as database:
        yield database


@pytest.fixture(scope="module")
def testing_session_local():
    """통합 테스트용 DB 세션 팩토리"""
    return TestingSessionLocal


# TestingSessionLocal 픽스처 (별칭)
TestingSessionLocal_fixture = testing_session_local


@pytest_asyncio.fixture(scope="function")
async def setup_test_db():
    """DB 초기화 (통합 테스트용)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
def test_client(setup_test_db):
    """TestClient (통합 테스트용)"""
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(
        app=app,
        base_url="http://testserver"
    )
    yield client
    app.dependency_overrides.clear()


def override_admin(user):
    """Admin 인증 오버라이드 헬퍼 (통합 테스트용, 픽스처 아님)"""
    def _override():
        return user
    return _override


@pytest_asyncio.fixture
async def admin_user():
    """관리자 사용자 (통합 테스트용)"""
    async with TestingSessionLocal() as db:
        user = User(
            username="admin_test",
            nickname="Admin",
            email="admin@test.com",
            hashed_password="hashed",
            is_admin=True
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


# ===== 공통 헬퍼 함수 =====


def create_test_pdf():
    """더미 PDF 파일 생성 헬퍼 (통합 테스트용, 픽스처 아님)"""
    pdf_content = b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n"
    pdf_content += b"%%EOF\n"
    return BytesIO(pdf_content)
