"""
Criteria Pipeline 통합 테스트: 문서 간 격리
Criteria 문서 간 Vector Store 격리 검증
"""
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy import select
from app.models.criteria import CriteriaDocument
from app.routers.auth import get_current_admin

from conftest import create_test_pdf, override_admin

class TestCriteriaDocumentsIsolation:
    """Criteria 문서 간 격리 검증"""

    @pytest.mark.asyncio
    async def test_criteria_documents_isolation(
        self,
        test_client,
        admin_user
    ):
        """
        Criteria 문서 간 격리 검증
        문서 A 활성화 시 문서 A 스토어만 사용
        문서 B 활성화 시 문서 B 스토어만 사용
        """
        # 1. 문서 A 업로드
        from app.main import app
        app.dependency_overrides[get_current_admin] = (
            override_admin(admin_user)
        )

        vector_id_a = "criteria-vector-doc-a"
        with patch(
            "app.services."
            "criteria_embedding_service."
            "CriteriaEmbeddingService."
            "upload_and_embed",
            new_callable=AsyncMock,
            return_value=vector_id_a
        ):
            files = {
                "file": (
                    "doc_a.pdf",
                    create_test_pdf(),
                    "application/pdf"
                )
            }
            response_a = test_client.post(
                "/admin/criteria/upload",
                files=files,
                data={"title": "Document A"}
            )

        criteria_id_a = response_a.json()["id"]

        # 2. 문서 B 업로드
        vector_id_b = "criteria-vector-doc-b"
        with patch(
            "app.services."
            "criteria_embedding_service."
            "CriteriaEmbeddingService."
            "upload_and_embed",
            new_callable=AsyncMock,
            return_value=vector_id_b
        ):
            files = {
                "file": (
                    "doc_b.pdf",
                    create_test_pdf(),
                    "application/pdf"
                )
            }
            response_b = test_client.post(
                "/admin/criteria/upload",
                files=files,
                data={"title": "Document B"}
            )

        criteria_id_b = response_b.json()["id"]
        app.dependency_overrides.pop(get_current_admin, None)

        # 3. DB에서 각 문서의 vector_store_id 확인
        async with TestingSessionLocal() as db:
            stmt = select(CriteriaDocument).where(
                CriteriaDocument.id == criteria_id_a
            )
            result = await db.execute(stmt)
            doc_a = result.scalar_one()

            stmt = select(CriteriaDocument).where(
                CriteriaDocument.id == criteria_id_b
            )
            result = await db.execute(stmt)
            doc_b = result.scalar_one()

            # 각 문서가 다른 Vector Store ID를 가지는지 확인
            assert doc_a.vector_store_id == vector_id_a
            assert doc_b.vector_store_id == vector_id_b
            assert (
                doc_a.vector_store_id
                != doc_b.vector_store_id
            )

        # 4. 문서 A 활성화
        app.dependency_overrides[get_current_admin] = (
            override_admin(admin_user)
        )
        test_client.post(
            f"/admin/criteria/{criteria_id_a}/activate"
        )

        # 5. active 문서가 A이고, A 스토어만 사용되는지 확인
        async with TestingSessionLocal() as db:
            stmt = select(CriteriaDocument).where(
                CriteriaDocument.status == "active"
            )
            result = await db.execute(stmt)
            active_doc = result.scalar_one_or_none()

            assert active_doc is not None
            assert active_doc.id == criteria_id_a
            assert (
                active_doc.vector_store_id
                == vector_id_a
            )

        # 6. 문서 B 활성화
        test_client.post(
            f"/admin/criteria/{criteria_id_b}/activate"
        )

        # 7. active 문서가 B이고, B 스토어만 사용되는지 확인
        async with TestingSessionLocal() as db:
            stmt = select(CriteriaDocument).where(
                CriteriaDocument.status == "active"
            )
            result = await db.execute(stmt)
            active_doc = result.scalar_one_or_none()

            assert active_doc is not None
            assert active_doc.id == criteria_id_b
            assert (
                active_doc.vector_store_id
                == vector_id_b
            )

            # 문서 A는 더 이상 active가 아님
            stmt = select(CriteriaDocument).where(
                CriteriaDocument.id == criteria_id_a
            )
            result = await db.execute(stmt)
            doc_a_after = result.scalar_one()
            assert doc_a_after.status == "uploaded"

        app.dependency_overrides.pop(get_current_admin, None)
