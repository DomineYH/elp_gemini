"""
의존성 주입 설정
FastAPI 의존성 함수 모음
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.criteria_repository import CriteriaRepository
from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService,
)


def get_criteria_repository(
    db: AsyncSession,
) -> CriteriaRepository:
    """
    CriteriaRepository 의존성 주입

    Args:
        db: 데이터베이스 세션

    Returns:
        CriteriaRepository 인스턴스
    """
    return CriteriaRepository(db)


def get_criteria_embedding_service() -> CriteriaEmbeddingService:
    """
    CriteriaEmbeddingService 의존성 주입

    Returns:
        CriteriaEmbeddingService 인스턴스
    """
    return CriteriaEmbeddingService()
