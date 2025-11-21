"""
평가 기준 삭제 통합 테스트
실제 DB와 API 엔드포인트를 사용한 테스트
"""
import os
import time
import uuid
import pytest
from pathlib import Path
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.db import get_db
from app.models.criteria import CriteriaDocument
from app.repositories.criteria_repository import CriteriaRepository


def generate_unique_store_id() -> str:
    """고유한 Vector Store ID 생성 (프로덕션 로직과 동일)"""
    timestamp = int(time.time() * 1000)
    unique_id = str(uuid.uuid4())[:8]
    return f"test-{timestamp}-{unique_id}"


@pytest.mark.asyncio
class TestCriteriaDeleteIntegration:
    """평가 기준 삭제 통합 테스트"""

    @pytest.fixture
    async def test_db(self):
        """테스트용 DB 세션"""
        # 실제 구현은 프로젝트의 테스트 설정에 따라 달라질 수 있음
        async for db in get_db():
            yield db

    @pytest.fixture
    async def sample_criteria(self, test_db: AsyncSession):
        """테스트용 샘플 평가 기준"""
        repo = CriteriaRepository(test_db)

        # 샘플 문서 생성 (고유한 vector_store_id 사용)
        doc = await repo.create(
            title="테스트 평가 기준",
            file_path="/tmp/test_criteria.pdf",
            mime_type="application/pdf",
            file_size=1024,
            vector_store_id=generate_unique_store_id(),
        )

        await test_db.commit()
        await test_db.refresh(doc)

        yield doc

        # 클린업 (테스트 후 삭제)
        try:
            await repo.delete_by_id(doc.id)
            await test_db.commit()
        except:
            pass

    async def test_delete_single_criteria(
        self, test_db: AsyncSession, sample_criteria: CriteriaDocument
    ):
        """개별 평가 기준 삭제 테스트"""
        repo = CriteriaRepository(test_db)

        # 삭제 전 문서 확인
        before_doc = await repo.get_by_id(sample_criteria.id)
        assert before_doc is not None

        # 삭제 실행
        deleted_doc = await repo.delete_by_id(sample_criteria.id)
        await test_db.commit()

        # 검증
        assert deleted_doc is not None
        assert deleted_doc.id == sample_criteria.id

        # 삭제 후 문서 확인
        after_doc = await repo.get_by_id(sample_criteria.id)
        assert after_doc is None

    async def test_delete_all_criteria(self, test_db: AsyncSession):
        """전체 평가 기준 삭제 테스트"""
        repo = CriteriaRepository(test_db)

        # 여러 개의 샘플 문서 생성 (각각 고유한 vector_store_id)
        for i in range(3):
            await repo.create(
                title=f"테스트 문서 {i+1}",
                file_path=f"/tmp/test_{i+1}.pdf",
                mime_type="application/pdf",
                file_size=1024 * (i + 1),
                vector_store_id=generate_unique_store_id(),
            )

        await test_db.commit()

        # 전체 삭제 실행
        deleted_count = await repo.delete_all()
        await test_db.commit()

        # 검증
        assert deleted_count >= 3

        # 삭제 후 확인
        documents, total = await repo.list_all()
        assert total == 0
        assert len(documents) == 0

    async def test_delete_api_endpoint(
        self, sample_criteria: CriteriaDocument
    ):
        """DELETE API 엔드포인트 테스트 (인증 포함)"""
        # 이 테스트는 실제 인증 토큰이 필요
        # 프로젝트의 인증 방식에 맞게 수정 필요

        async with AsyncClient(
            app=app, base_url="http://test"
        ) as client:
            # 관리자 로그인 (실제 구현에 맞게 수정)
            # login_response = await client.post("/auth/login", ...)
            # token = login_response.json()["access_token"]

            # 삭제 요청 (인증 헤더 포함)
            # response = await client.delete(
            #     f"/admin/criteria/{sample_criteria.id}",
            #     headers={"Authorization": f"Bearer {token}"}
            # )

            # assert response.status_code == 200
            # assert response.json()["success"] is True

            pass  # 실제 인증 구현 후 활성화

    async def test_delete_active_criteria(
        self, test_db: AsyncSession
    ):
        """활성 평가 기준 삭제 테스트"""
        repo = CriteriaRepository(test_db)

        # 샘플 문서 생성 (고유한 vector_store_id)
        doc = await repo.create(
            title="활성 테스트 문서",
            file_path="/tmp/active_test.pdf",
            mime_type="application/pdf",
            file_size=2048,
            vector_store_id=generate_unique_store_id(),
        )

        await test_db.commit()

        # 문서 활성화 (관리자 ID 1 사용)
        await repo.activate_criteria(doc.id, admin_id=1)
        await test_db.commit()

        # 활성 상태 확인
        active_doc = await repo.get_active()
        assert active_doc is not None
        assert active_doc.id == doc.id

        # 삭제 실행
        deleted_doc = await repo.delete_by_id(doc.id)
        await test_db.commit()

        # 검증
        assert deleted_doc is not None

        # 활성 기준이 없어졌는지 확인
        after_active = await repo.get_active()
        assert after_active is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
