"""
평가 기준 Vector Store 수명 관리 서비스
고아 스토어 정리 및 자동 삭제 정책 구현
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.criteria import CriteriaDocument
from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService,
)

logger = logging.getLogger(__name__)


class CriteriaStoreLifecycleService:
    """Vector Store 수명 관리 서비스"""

    def __init__(self, db: AsyncSession):
        """
        CriteriaStoreLifecycleService 초기화

        Args:
            db: 비동기 DB 세션
        """
        self.db = db
        self.embedding_service = CriteriaEmbeddingService()

    async def cleanup_old_stores(
        self, days: int = 30
    ) -> Dict[str, Any]:
        """
        N일 이상 비활성 스토어 자동 삭제

        Args:
            days: 삭제 기준일 (기본 30일)

        Returns:
            {
                "deleted_count": 삭제된 스토어 수,
                "failed_count": 삭제 실패 수,
                "deleted_stores": [스토어 ID 목록],
                "failed_stores": [{"store_id": ..., "error": ...}]
            }

        Raises:
            없음 (모든 예외를 내부에서 처리)
        """
        cutoff_date = datetime.now() - timedelta(days=days)

        # DB에서 오래된 문서 조회
        stmt = select(CriteriaDocument).where(
            CriteriaDocument.created_at < cutoff_date,
            CriteriaDocument.status == "uploaded",
        )
        result = await self.db.execute(stmt)
        old_docs = result.scalars().all()

        logger.info(
            f"자동 정리 시작: {len(old_docs)}개 문서 "
            f"({days}일 이상 비활성)"
        )

        deleted = []
        failed = []

        for doc in old_docs:
            try:
                # Vector Store 삭제
                success = await self.embedding_service.delete_store(
                    doc.vector_store_id, ignore_errors=False
                )

                if success:
                    # DB에서 문서 삭제
                    await self.db.delete(doc)
                    deleted.append(doc.vector_store_id)

                    logger.info(
                        f"오래된 스토어 삭제: {doc.title} "
                        f"(생성일: {doc.created_at})"
                    )

            except Exception as e:
                failed.append(
                    {"store_id": doc.vector_store_id, "error": str(e)}
                )
                logger.error(
                    f"스토어 삭제 실패: "
                    f"{doc.vector_store_id} - {e}"
                )

        await self.db.commit()

        logger.info(
            f"자동 정리 완료: {len(deleted)}개 삭제, "
            f"{len(failed)}개 실패"
        )

        return {
            "deleted_count": len(deleted),
            "failed_count": len(failed),
            "deleted_stores": deleted,
            "failed_stores": failed,
        }

    async def find_orphaned_stores(self) -> List[str]:
        """
        고아 스토어 검색
        (DB에 없지만 Google에 존재하는 스토어)

        Returns:
            고아 스토어 ID 목록

        Raises:
            Exception: Google API 오류 시
        """
        # DB의 모든 vector_store_id 조회
        stmt = select(CriteriaDocument.vector_store_id)
        result = await self.db.execute(stmt)
        valid_ids = set(result.scalars().all())

        logger.info(
            f"DB에 등록된 스토어: {len(valid_ids)}개"
        )

        # Google의 모든 스토어 조회
        client = self.embedding_service.client
        all_stores = client.file_search_stores.list()

        # 고아 스토어 필터링
        orphaned = []
        for store in all_stores:
            # criteria- 프리픽스 확인 (Criteria 스토어만)
            store_name = store.display_name
            store_id = store.name

            if (
                store_name.startswith("criteria-")
                and store_id not in valid_ids
            ):
                orphaned.append(store_id)
                logger.debug(
                    f"고아 스토어 발견: {store_id} "
                    f"({store_name})"
                )

        logger.info(f"고아 스토어 {len(orphaned)}개 발견")

        return orphaned

    async def get_store_statistics(self) -> Dict[str, Any]:
        """
        스토어 통계 조회

        Returns:
            {
                "total_stores": 전체 스토어 수,
                "active_stores": 활성 스토어 수,
                "uploaded_stores": 업로드 상태 스토어 수,
                "oldest_store_date": 가장 오래된 스토어 날짜
            }

        Raises:
            없음 (오류 시 빈 Dict 반환)
        """
        try:
            # 전체 스토어 수
            stmt = select(CriteriaDocument)
            result = await self.db.execute(stmt)
            all_docs = result.scalars().all()

            if not all_docs:
                logger.warning("스토어가 없습니다")
                return {
                    "total_stores": 0,
                    "active_stores": 0,
                    "uploaded_stores": 0,
                    "oldest_store_date": None,
                }

            # 상태별 집계
            active = sum(
                1 for doc in all_docs if doc.status == "active"
            )
            uploaded = sum(
                1 for doc in all_docs if doc.status == "uploaded"
            )

            # 가장 오래된 스토어
            oldest = min(
                (doc.created_at for doc in all_docs), default=None
            )

            stats = {
                "total_stores": len(all_docs),
                "active_stores": active,
                "uploaded_stores": uploaded,
                "oldest_store_date": (
                    oldest.isoformat() if oldest else None
                ),
            }

            logger.info(
                f"스토어 통계: 전체 {stats['total_stores']}개, "
                f"활성 {stats['active_stores']}개, "
                f"업로드 {stats['uploaded_stores']}개"
            )

            return stats

        except Exception as e:
            logger.error(f"스토어 통계 조회 실패: {e}")
            return {}
