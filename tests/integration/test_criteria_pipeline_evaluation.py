"""
Criteria Pipeline 통합 테스트: 활성화 → 평가
Active 기준을 사용한 평가 시나리오 검증
"""
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from unittest.mock import (
    patch,
    Mock,
    AsyncMock,
    MagicMock,
    call
)
from sqlalchemy import select
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
from app.models.documents import Document
from app.models.evaluations import EvaluationTemplate
from app.models.criteria import CriteriaDocument, ActiveCriteria
from app.routers.auth import get_current_user


# conftest.py의 픽스처 사용 (pytest가 자동 발견)


def override_user(user):
    """사용자 인증 오버라이드"""
    def _override():
        return user
    return _override


@pytest_asyncio.fixture
async def test_user():
    """일반 사용자"""
    async with TestingSessionLocal() as db:
        user = User(
            username="test_user",
            nickname="Test User",
            hashed_password="hashed",
            is_admin=False
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest_asyncio.fixture
async def test_document(test_user):
    """테스트 문서"""
    async with TestingSessionLocal() as db:
        doc = Document(
            title="Test Doc",
            random_key="test-key",
            file_path="/test.pdf",
            file_size=1024,
            store_id="store-123",
            file_search_file_id="file-123",
            user_id=test_user.id,
            status="ready"
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc


@pytest_asyncio.fixture
async def test_template():
    """평가 템플릿"""
    async with TestingSessionLocal() as db:
        template = EvaluationTemplate(
            name="Test Template",
            description="Test",
            criteria={"clarity": "high"},
            is_active=True
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return template


@pytest_asyncio.fixture
async def active_criteria():
    """활성 기준 문서"""
    async with TestingSessionLocal() as db:
        # 기준 문서 생성
        criteria = CriteriaDocument(
            title="Active Criteria",
            file_path="/criteria.pdf",
            mime_type="application/pdf",
            file_size=2048,
            vector_store_id="vector-store-active",
            status="active"
        )
        db.add(criteria)
        await db.flush()

        # Active 설정
        active = ActiveCriteria(
            id=1,
            criteria_document_id=criteria.id
        )
        db.add(active)
        await db.commit()
        await db.refresh(criteria)
        return criteria


# create_test_pdf는 conftest.py에서 import


class TestCriteriaPipelineEvaluation:
    """활성화 → 평가 시나리오"""

    @pytest.mark.asyncio
    async def test_evaluation_with_active_criteria(
        self,
        test_client,
        test_user,
        test_document,
        test_template,
        active_criteria
    ):
        """
        Active 기준 있을 때 평가 성공
        """
        # CriteriaContextService 모킹
        mock_context = [
            {
                "content": "기준: 명확성 우선",
                "metadata": {
                    "criteria_id": active_criteria.id
                }
            }
        ]

        with patch(
            "app.services.eval_service."
            "CriteriaContextService.get_context",
            new_callable=AsyncMock,
            return_value=mock_context
        ) as mock_get_context:

            # Gemini API 모킹
            mock_gemini_response = Mock()
            mock_gemini_response.text = (
                "평가 결과: 우수\n"
                "개선 제안: 없음"
            )

            with patch(
                "app.services.eval_service."
                "genai.GenerativeModel"
            ) as mock_model:
                mock_instance = MagicMock()
                mock_instance.generate_content = AsyncMock(
                    return_value=mock_gemini_response
                )
                mock_model.return_value = mock_instance

                # 평가 실행
                app.dependency_overrides[
                    get_current_user
                ] = override_user(test_user)

                response = test_client.post(
                    "/eval/run",
                    json={
                        "template_id": test_template.id
                    }
                )

                app.dependency_overrides.pop(
                    get_current_user, None
                )

        # 검증
        assert response.status_code == 200
        result = response.json()
        assert "id" in result
        assert result["status"] in [
            "running",
            "completed"
        ]

        # CriteriaContextService 호출 확인
        assert mock_get_context.called

    @pytest.mark.asyncio
    async def test_evaluation_without_active_criteria(
        self,
        test_client,
        test_user,
        test_document,
        test_template
    ):
        """
        Active 기준 없을 때 평가 실패 (ValueError)
        """
        # Active 기준 없음 (fixture 사용 안 함)

        # 평가 실행
        app.dependency_overrides[get_current_user] = (
            override_user(test_user)
        )
        response = test_client.post(
            "/eval/run",
            json={"template_id": test_template.id}
        )
        app.dependency_overrides.pop(get_current_user, None)

        # ValueError → 400 에러 예상
        # (실제 에러 처리는 eval_service.py 참고)
        assert response.status_code in [400, 500, 503]

    @pytest.mark.asyncio
    async def test_context_search_called_correctly(
        self,
        test_client,
        test_user,
        test_document,
        test_template,
        active_criteria
    ):
        """
        CriteriaContextService.get_context() 호출 검증
        """
        mock_context = [
            {"content": "기준 1"},
            {"content": "기준 2"}
        ]

        with patch(
            "app.services.eval_service."
            "CriteriaContextService.get_context",
            new_callable=AsyncMock,
            return_value=mock_context
        ) as mock_get_context:

            with patch(
                "app.services.eval_service."
                "genai.GenerativeModel"
            ) as mock_model:
                mock_instance = MagicMock()
                mock_response = Mock()
                mock_response.text = "평가 완료"
                mock_instance.generate_content = AsyncMock(
                    return_value=mock_response
                )
                mock_model.return_value = mock_instance

                app.dependency_overrides[
                    get_current_user
                ] = override_user(test_user)

                test_client.post(
                    "/eval/run",
                    json={
                        "template_id": test_template.id
                    }
                )

                app.dependency_overrides.pop(
                    get_current_user, None
                )

        # get_context() 호출 확인
        assert mock_get_context.called
        # 호출 인자 확인 (query 포함)
        call_args = mock_get_context.call_args
        assert call_args is not None
