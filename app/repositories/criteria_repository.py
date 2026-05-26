"""
평가기준 레포지토리
Criteria 데이터 액세스 레이어
"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
import logging

from app.models.criteria import Criteria

logger = logging.getLogger(__name__)


class CriteriaRepository:
    """평가기준 레포지토리 클래스"""

    def __init__(self, db: AsyncSession):
        """
        초기화

        Args:
            db: 데이터베이스 세션
        """
        self.db = db

    async def save_criteria(
        self,
        title: str,
        file_size: int,
        uploaded_by: str,
        file_path: str,
        document_id: Optional[str] = None,
        status: str = "uploaded",
    ) -> Criteria:
        """
        새 평가기준 저장

        Args:
            title: 파일명/제목
            file_size: 파일 크기 (바이트)
            uploaded_by: 업로드한 관리자 사용자명
            file_path: 로컬 파일 경로
            document_id: Vector Store 문서 ID (선택)
            status: 상태 (기본값: uploaded)

        Returns:
            생성된 Criteria 객체
        """
        criteria = Criteria(
            title=title,
            file_size=file_size,
            uploaded_by=uploaded_by,
            file_path=file_path,
            document_id=document_id,
            status=status,
        )
        self.db.add(criteria)
        await self.db.flush()

        logger.info(
            f"평가기준 저장: id={criteria.id}, "
            f"title={title}, "
            f"file_path={file_path}"
        )
        return criteria

    async def get_all_criteria(self) -> List[Criteria]:
        """
        모든 평가기준 조회

        Returns:
            Criteria 리스트
        """
        result = await self.db.execute(
            select(Criteria)
            .order_by(Criteria.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active_criteria(self) -> List[Criteria]:
        """
        활성 상태 평가기준만 조회

        Returns:
            active 상태인 Criteria 리스트
        """
        result = await self.db.execute(
            select(Criteria)
            .where(Criteria.status == "active")
            .order_by(Criteria.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_criteria_by_id(
        self, criteria_id: int
    ) -> Optional[Criteria]:
        """
        ID로 평가기준 조회

        Args:
            criteria_id: 평가기준 ID

        Returns:
            Criteria 객체 또는 None
        """
        result = await self.db.execute(
            select(Criteria)
            .where(Criteria.id == criteria_id)
        )
        return result.scalar_one_or_none()

    async def get_criteria_by_document_id(
        self, document_id: str
    ) -> Optional[Criteria]:
        """
        Vector Store 문서 ID로 평가기준 조회

        Args:
            document_id: Vector Store 문서 ID

        Returns:
            Criteria 객체 또는 None
        """
        result = await self.db.execute(
            select(Criteria)
            .where(Criteria.document_id == document_id)
        )
        return result.scalar_one_or_none()

    async def get_criteria_by_stable_id(
        self, stable_id: str
    ) -> Optional[Criteria]:
        """
        stable_id로 평가기준 1행을 조회

        Args:
            stable_id: 클라우드 진실의 원천 고유 ID (ULID)

        Returns:
            Criteria 객체 또는 None
        """
        result = await self.db.execute(
            select(Criteria)
            .where(Criteria.stable_id == stable_id)
        )
        return result.scalar_one_or_none()

    async def delete_criteria(
        self, criteria_id: int
    ) -> bool:
        """
        평가기준 삭제

        Args:
            criteria_id: 평가기준 ID

        Returns:
            삭제 성공 여부
        """
        result = await self.db.execute(
            delete(Criteria)
            .where(Criteria.id == criteria_id)
        )
        deleted_count = result.rowcount

        if deleted_count > 0:
            logger.info(
                f"평가기준 삭제: id={criteria_id}"
            )
            return True
        else:
            logger.warning(
                f"평가기준 삭제 실패 (없음): id={criteria_id}"
            )
            return False

    async def delete_all_criteria(self) -> int:
        """
        모든 평가기준 삭제

        Returns:
            삭제된 레코드 수
        """
        result = await self.db.execute(delete(Criteria))
        deleted_count = result.rowcount

        logger.info(
            f"모든 평가기준 삭제: {deleted_count}개"
        )
        return deleted_count

    async def update_status(
        self, criteria_id: int, status: str
    ) -> Optional[Criteria]:
        """
        평가기준 상태 업데이트

        Args:
            criteria_id: 평가기준 ID
            status: 새로운 상태

        Returns:
            업데이트된 Criteria 객체 또는 None
        """
        criteria = await self.get_criteria_by_id(criteria_id)

        if not criteria:
            logger.warning(
                f"평가기준 상태 업데이트 실패 (없음): "
                f"id={criteria_id}"
            )
            return None

        criteria.status = status
        await self.db.flush()

        logger.info(
            f"평가기준 상태 업데이트: "
            f"id={criteria_id}, status={status}"
        )
        return criteria

    async def activate_criteria(
        self, criteria_id: int
    ) -> Optional[Criteria]:
        """
        평가기준 활성화 (상태를 active로 변경 및 activated_at 설정)

        Args:
            criteria_id: 평가기준 ID

        Returns:
            업데이트된 Criteria 객체 또는 None
        """
        criteria = await self.get_criteria_by_id(criteria_id)

        if not criteria:
            logger.warning(
                f"평가기준 활성화 실패 (없음): "
                f"id={criteria_id}"
            )
            return None

        criteria.status = "active"
        criteria.activated_at = datetime.utcnow()
        await self.db.flush()

        logger.info(
            f"평가기준 활성화: "
            f"id={criteria_id}, activated_at={criteria.activated_at}"
        )
        return criteria

    async def deactivate_criteria(
        self, criteria_id: int
    ) -> Optional[Criteria]:
        """
        평가기준 비활성화 (상태를 uploaded로 변경)

        Args:
            criteria_id: 평가기준 ID

        Returns:
            업데이트된 Criteria 객체 또는 None
        """
        criteria = await self.get_criteria_by_id(criteria_id)

        if not criteria:
            logger.warning(
                f"평가기준 비활성화 실패 (없음): "
                f"id={criteria_id}"
            )
            return None

        criteria.status = "uploaded"
        # activated_at은 유지 (이력 보존)
        await self.db.flush()

        logger.info(
            f"평가기준 비활성화: "
            f"id={criteria_id}"
        )
        return criteria

    async def update_document_id(
        self, criteria_id: int, document_id: str
    ) -> Optional[Criteria]:
        """
        평가기준의 document_id 업데이트

        Args:
            criteria_id: 평가기준 ID
            document_id: Vector Store 문서 ID

        Returns:
            업데이트된 Criteria 객체 또는 None
        """
        criteria = await self.get_criteria_by_id(criteria_id)

        if not criteria:
            logger.warning(
                f"평가기준 document_id 업데이트 실패 (없음): "
                f"id={criteria_id}"
            )
            return None

        criteria.document_id = document_id
        await self.db.flush()

        logger.info(
            f"평가기준 document_id 업데이트: "
            f"id={criteria_id}, document_id={document_id}"
        )
        return criteria

    async def update_display_alias(
        self,
        criteria_id: int,
        alias: Optional[str],
    ) -> Optional[Criteria]:
        """
        criteria.display_alias 업데이트

        Args:
            criteria_id: 평가기준 ID
            alias: 새로운 display_alias 값

        Returns:
            업데이트된 Criteria 객체 또는 None
        """
        criteria = await self.get_criteria_by_id(criteria_id)
        if criteria is None:
            logger.warning(
                f"display_alias 업데이트 실패 (없음): "
                f"id={criteria_id}"
            )
            return None
        criteria.display_alias = alias
        await self.db.flush()
        await self.db.refresh(criteria)

        logger.info(
            f"평가기준 display_alias 업데이트: "
            f"id={criteria_id}, alias={alias}"
        )
        return criteria

    async def get_criteria_map_by_document_ids(
        self,
        doc_ids: List[str],
    ) -> dict[str, Criteria]:
        """
        document_id 리스트로 Criteria를 일괄 조회하여 dict로 반환

        Args:
            doc_ids: 클라우드 문서 ID 목록

        Returns:
            { document_id: Criteria } — 매칭되지 않는 ID는 키에 포함되지 않음
        """
        if not doc_ids:
            return {}
        stmt = select(Criteria).where(
            Criteria.document_id.in_(doc_ids)
        )
        result = await self.db.execute(stmt)
        return {c.document_id: c for c in result.scalars().all()}

    async def truncate(self) -> None:
        """모든 criteria 행 삭제."""
        await self.db.execute(delete(Criteria))
        await self.db.flush()
        logger.info("criteria 테이블 truncate 완료")

    async def bulk_insert(self, rows: list[dict]) -> None:
        """dict 리스트를 Criteria 객체로 일괄 삽입."""
        for row in rows:
            self.db.add(Criteria(**row))
        await self.db.flush()
        logger.info("criteria bulk insert 완료: %d건", len(rows))

    async def insert(
        self,
        *,
        stable_id: str,
        document_id: str,
        title: str,
        display_alias: Optional[str],
        status: str,
        created_at: Optional[str],
        activated_at: Optional[str],
        uploaded_by: str = "cloud-sync",
    ) -> None:
        """reconcile에서 사용. 호출자가 트랜잭션을 관리."""
        row = Criteria(
            stable_id=stable_id,
            document_id=document_id,
            title=title,
            display_alias=display_alias,
            status=status,
            file_size=0,
            file_path="",
            uploaded_by=uploaded_by,
        )
        if created_at:
            try:
                row.created_at = datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                )
            except Exception:
                pass
        if activated_at:
            try:
                row.activated_at = datetime.fromisoformat(
                    activated_at.replace("Z", "+00:00")
                )
            except Exception:
                pass
        self.db.add(row)

    async def upsert_from_cloud(
        self,
        *,
        stable_id: str,
        document_id: str,
        title: str,
        display_alias: Optional[str],
        status: str,
        created_at: Optional[str],
        activated_at: Optional[str],
    ) -> None:
        """
        cloud truth로부터 row를 upsert. 기존 행이 있으면 cloud-소스 필드만
        업데이트하여 uploaded_by / file_size / file_path 등 local-only 컬럼을
        보존한다. 호출자가 트랜잭션을 관리한다.
        """
        existing = await self.get_criteria_by_stable_id(stable_id)
        created_dt = None
        if created_at:
            try:
                created_dt = datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                )
            except Exception:
                created_dt = None
        activated_dt = None
        if activated_at:
            try:
                activated_dt = datetime.fromisoformat(
                    activated_at.replace("Z", "+00:00")
                )
            except Exception:
                activated_dt = None

        if existing is not None:
            existing.document_id = document_id
            existing.title = title
            existing.display_alias = display_alias
            existing.status = status
            if created_dt is not None:
                existing.created_at = created_dt
            existing.activated_at = activated_dt
            await self.db.flush()
            return

        row = Criteria(
            stable_id=stable_id,
            document_id=document_id,
            title=title,
            display_alias=display_alias,
            status=status,
            file_size=0,
            file_path="",
            uploaded_by="cloud-sync",
        )
        if created_dt is not None:
            row.created_at = created_dt
        if activated_dt is not None:
            row.activated_at = activated_dt
        self.db.add(row)
        await self.db.flush()

    async def delete_by_stable_ids_except(
        self, keep_stable_ids: set[str]
    ) -> int:
        """주어진 stable_id 집합에 없는 행을 모두 삭제. 호출자가 트랜잭션 관리."""
        if keep_stable_ids:
            stmt = delete(Criteria).where(
                (
                    Criteria.stable_id.notin_(keep_stable_ids)
                ) | Criteria.stable_id.is_(None)
            )
        else:
            stmt = delete(Criteria)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount or 0
