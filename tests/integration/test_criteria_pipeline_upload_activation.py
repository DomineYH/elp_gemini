"""
Criteria Pipeline 통합 테스트
업로드 → 활성화 → 평가 파이프라인 전체 검증
User Vector DB 격리 보장 확인
"""
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock, AsyncMock, MagicMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker
)
from sqlalchemy.pool import StaticPool
import tempfile
import os
from pathlib import Path
from io import BytesIO

from app.main import app
from app.db import Base, get_db
from app.models.users import User
from app.models.criteria import CriteriaDocument, ActiveCriteria
from app.routers.auth import get_current_admin


# conftest.py의 픽스처 사용 (pytest가 자동 발견)

from conftest import create_test_pdf, override_admin

class TestCriteriaPipelineUploadActivation:
    """업로드 → 활성화 통합 시나리오"""

    @pytest.mark.asyncio
    async def test_upload_and_activate_success(
        self,
        test_client,
        admin_user
    ):
        """
        정상 흐름: PDF 업로드 → 활성화 → 단일 Active 검증
        """
        pytest.skip("Wave 5: replaced by stable_id-based routes")
        # 1. 업로드 준비
        pdf_file = create_test_pdf()
        files = {
            "file": (
                "test_criteria.pdf",
                pdf_file,
                "application/pdf"
            )
        }
        data = {"title": "Test Evaluation Criteria"}

        # 2. Admin 인증 오버라이드
        app.dependency_overrides[get_current_admin] = (
            override_admin(admin_user)
        )

        # 3. Google File Search Tool 모킹
        mock_vector_id = "vector-store-test-123"
        with patch(
            "app.services."
            "criteria_embedding_service."
            "CriteriaEmbeddingService."
            "upload_and_embed",
            new_callable=AsyncMock
        ) as mock_embed:
            mock_embed.return_value = mock_vector_id

            # 4. 업로드 API 호출
            response = test_client.post(
                "/admin/criteria/upload",
                files=files,
                data=data
            )

        # 인증 오버라이드 제거
        app.dependency_overrides.pop(get_current_admin, None)

        # 4. 업로드 성공 검증
        assert response.status_code == 200
        upload_result = response.json()
        assert "id" in upload_result
        criteria_id = upload_result["id"]
        assert upload_result["title"] == data["title"]
        assert (
            upload_result["vector_store_id"] == mock_vector_id
        )
        assert upload_result["status"] == "uploaded"

        # 5. DB에 저장 확인
        async with TestingSessionLocal() as db:
            stmt = select(CriteriaDocument).where(
                CriteriaDocument.id == criteria_id
            )
            result = await db.execute(stmt)
            doc = result.scalar_one_or_none()
            assert doc is not None
            assert doc.title == data["title"]
            assert doc.vector_store_id == mock_vector_id

        # 6. 활성화 API 호출
        app.dependency_overrides[get_current_admin] = (
            override_admin(admin_user)
        )
        activate_response = test_client.post(
            f"/admin/criteria/{criteria_id}/activate"
        )
        app.dependency_overrides.pop(get_current_admin, None)

        # 7. 활성화 성공 검증
        assert activate_response.status_code == 200
        activate_result = activate_response.json()
        assert (
            activate_result["criteria_id"]
            == criteria_id
        )

        # 8. Active 상태 DB 확인
        async with TestingSessionLocal() as db:
            # 문서 상태 확인
            stmt = select(CriteriaDocument).where(
                CriteriaDocument.id == criteria_id
            )
            result = await db.execute(stmt)
            doc = result.scalar_one_or_none()
            assert doc.status == "active"

            # Active 테이블 확인
            stmt = select(ActiveCriteria).where(
                ActiveCriteria.id == 1
            )
            result = await db.execute(stmt)
            active = result.scalar_one_or_none()
            assert active is not None
            assert (
                active.criteria_document_id == criteria_id
            )

    @pytest.mark.asyncio
    async def test_activate_replaces_previous_active(
        self,
        test_client,
        admin_user
    ):
        """
        단일 Active 보장: 새 문서 활성화 시
        기존 Active 자동 비활성화
        """
        pytest.skip("Wave 5: replaced by stable_id-based routes")
        # 1. 첫 번째 문서 업로드
        app.dependency_overrides[get_current_admin] = (
            override_admin(admin_user)
        )

        mock_vector_id_1 = "vector-store-1"
        with patch(
            "app.services."
            "criteria_embedding_service."
            "CriteriaEmbeddingService."
            "upload_and_embed",
            new_callable=AsyncMock,
            return_value=mock_vector_id_1
        ):
            files = {
                "file": (
                    "criteria1.pdf",
                    create_test_pdf(),
                    "application/pdf"
                )
            }
            response1 = test_client.post(
                "/admin/criteria/upload",
                files=files,
                data={"title": "Criteria 1"}
            )

        criteria_id_1 = response1.json()["id"]

        # 첫 번째 문서 활성화
        test_client.post(
            f"/admin/criteria/{criteria_id_1}/activate"
        )
        app.dependency_overrides.pop(get_current_admin, None)

        # 2. 두 번째 문서 업로드
        app.dependency_overrides[get_current_admin] = (
            override_admin(admin_user)
        )

        mock_vector_id_2 = "vector-store-2"
        with patch(
            "app.services."
            "criteria_embedding_service."
            "CriteriaEmbeddingService."
            "upload_and_embed",
            new_callable=AsyncMock,
            return_value=mock_vector_id_2
        ):
            files = {
                "file": (
                    "criteria2.pdf",
                    create_test_pdf(),
                    "application/pdf"
                )
            }
            response2 = test_client.post(
                "/admin/criteria/upload",
                files=files,
                data={"title": "Criteria 2"}
            )

        criteria_id_2 = response2.json()["id"]

        # 3. 두 번째 문서 활성화
        test_client.post(
            f"/admin/criteria/{criteria_id_2}/activate"
        )
        app.dependency_overrides.pop(get_current_admin, None)

        # 4. 단일 Active 검증
        async with TestingSessionLocal() as db:
            # Active 테이블: 오직 하나만 존재
            stmt = select(ActiveCriteria)
            result = await db.execute(stmt)
            actives = result.scalars().all()
            assert len(actives) == 1
            assert (
                actives[0].criteria_document_id
                == criteria_id_2
            )

            # 첫 번째 문서: uploaded로 복귀
            stmt = select(CriteriaDocument).where(
                CriteriaDocument.id == criteria_id_1
            )
            result = await db.execute(stmt)
            doc1 = result.scalar_one()
            assert doc1.status == "uploaded"
            assert doc1.vector_store_id == mock_vector_id_1

            # 두 번째 문서: active
            stmt = select(CriteriaDocument).where(
                CriteriaDocument.id == criteria_id_2
            )
            result = await db.execute(stmt)
            doc2 = result.scalar_one()
            assert doc2.status == "active"
            assert doc2.vector_store_id == mock_vector_id_2

            # 각 문서가 고유한 vector_store_id를 가지는지 확인
            assert doc1.vector_store_id != doc2.vector_store_id
