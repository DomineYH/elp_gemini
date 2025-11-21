"""
평가 기준 Repository
CriteriaDocument CRUD 작업 관리
"""
from typing import Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError

from app.models.criteria import CriteriaDocument, ActiveCriteria


class CriteriaRepository:
    """평가 기준 문서 Repository"""

    def __init__(self, db: AsyncSession):
        """
        Repository 초기화

        Args:
            db: 비동기 데이터베이스 세션
        """
        self.db = db

    async def create(
        self,
        title: str,
        file_path: str,
        mime_type: str,
        file_size: int,
        vector_store_id: str,
        document_id: Optional[str] = None,
    ) -> CriteriaDocument:
        """
        새 평가 기준 문서 생성

        Args:
            title: 문서 제목
            file_path: 파일 저장 경로
            mime_type: MIME 타입
            file_size: 파일 크기 (bytes)
            vector_store_id: Google File Search Store ID
            document_id: Google File Search Document ID (선택)

        Returns:
            생성된 CriteriaDocument 객체

        Raises:
            IntegrityError: vector_store_id 중복 시
        """
        document = CriteriaDocument(
            title=title,
            file_path=file_path,
            mime_type=mime_type,
            file_size=file_size,
            vector_store_id=vector_store_id,
            document_id=document_id,
            status="uploaded",
        )
        self.db.add(document)
        await self.db.flush()
        await self.db.refresh(document)
        return document

    async def get_by_id(
        self, criteria_id: int
    ) -> Optional[CriteriaDocument]:
        """
        ID로 기준 문서 조회

        Args:
            criteria_id: 기준 문서 ID

        Returns:
            CriteriaDocument 또는 None
        """
        result = await self.db.execute(
            select(CriteriaDocument).where(
                CriteriaDocument.id == criteria_id
            )
        )
        return result.scalar_one_or_none()

    async def list_all(
        self, page: int = 1, page_size: int = 20
    ) -> tuple[list[CriteriaDocument], int]:
        """
        전체 기준 문서 목록 조회 (페이지네이션)

        Args:
            page: 페이지 번호 (1부터 시작)
            page_size: 페이지 크기

        Returns:
            (문서 목록, 전체 개수) 튜플
        """
        # 전체 개수 조회
        count_result = await self.db.execute(
            select(func.count(CriteriaDocument.id))
        )
        total = count_result.scalar() or 0

        # 페이지네이션 적용 목록 조회
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(CriteriaDocument)
            .order_by(CriteriaDocument.created_at.desc())
            .limit(page_size)
            .offset(offset)
        )
        documents = result.scalars().all()

        return list(documents), total

    async def update_status(
        self, criteria_id: int, status: str
    ) -> Optional[CriteriaDocument]:
        """
        기준 문서 상태 업데이트

        Args:
            criteria_id: 기준 문서 ID
            status: 새 상태 (uploaded|active|archived|error)

        Returns:
            업데이트된 CriteriaDocument 또는 None

        Raises:
            ValueError: 유효하지 않은 상태값
        """
        valid_statuses = {"uploaded", "active", "archived", "error"}
        if status not in valid_statuses:
            raise ValueError(
                f"Invalid status: {status}. "
                f"Must be one of {valid_statuses}"
            )

        document = await self.get_by_id(criteria_id)
        if document:
            document.status = status
            await self.db.flush()
            await self.db.refresh(document)

        return document

    async def get_active(self) -> Optional[CriteriaDocument]:
        """
        현재 활성화된 기준 문서 조회

        Returns:
            활성 CriteriaDocument 또는 None
        """
        result = await self.db.execute(
            select(CriteriaDocument).where(
                CriteriaDocument.status == "active"
            )
        )
        return result.scalar_one_or_none()

    async def activate_criteria(
        self, criteria_id: int, admin_id: int
    ) -> CriteriaDocument:
        """
        평가 기준 문서 활성화 (트랜잭션)

        기존 활성 문서를 비활성화하고 새 문서를 활성화합니다.
        active_criteria 테이블에 단일 활성 상태를 기록합니다.

        Args:
            criteria_id: 활성화할 기준 문서 ID
            admin_id: 활성화를 수행한 관리자 ID

        Returns:
            활성화된 CriteriaDocument

        Raises:
            ValueError: 문서가 존재하지 않을 때
        """
        # 1. 활성화할 문서 존재 확인
        document = await self.get_by_id(criteria_id)
        if not document:
            raise ValueError(
                f"Criteria document {criteria_id} not found"
            )

        # 2. 기존 활성 문서 비활성화
        await self.db.execute(
            update(CriteriaDocument)
            .where(CriteriaDocument.status == "active")
            .values(status="uploaded", activated_at=None)
        )

        # 3. 새 문서 활성화
        now = datetime.utcnow()
        document.status = "active"
        document.activated_at = now
        document.activated_by = admin_id

        # 4. active_criteria 테이블 upsert (id=1 고정)
        active_result = await self.db.execute(
            select(ActiveCriteria).where(ActiveCriteria.id == 1)
        )
        active_record = active_result.scalar_one_or_none()

        if active_record:
            # 기존 레코드 업데이트
            active_record.criteria_document_id = criteria_id
            active_record.activated_at = now
            active_record.activated_by = admin_id
        else:
            # 새 레코드 생성
            active_record = ActiveCriteria(
                id=1,
                criteria_document_id=criteria_id,
                activated_at=now,
                activated_by=admin_id,
            )
            self.db.add(active_record)

        await self.db.flush()
        await self.db.refresh(document)
        return document

    async def deactivate_all(self) -> Optional[int]:
        """
        현재 활성 기준 문서 비활성화

        Returns:
            비활성화된 문서 ID 또는 None
        """
        # 현재 활성 문서 조회
        active_doc = await self.get_active()

        if not active_doc:
            return None

        # 문서 상태 변경
        active_doc.status = "uploaded"
        active_doc.activated_at = None
        active_doc.activated_by = None

        # active_criteria 테이블 업데이트
        result = await self.db.execute(
            select(ActiveCriteria).where(ActiveCriteria.id == 1)
        )
        active_record = result.scalar_one_or_none()

        if active_record:
            active_record.criteria_document_id = None
            active_record.activated_at = None
            active_record.activated_by = None

        await self.db.flush()
        return active_doc.id

    async def delete_by_id(
        self, criteria_id: int
    ) -> Optional[CriteriaDocument]:
        """
        ID로 평가 기준 문서 삭제

        Args:
            criteria_id: 삭제할 기준 문서 ID

        Returns:
            삭제된 CriteriaDocument 또는 None

        Note:
            활성 상태인 문서를 삭제하면 active_criteria 테이블도 업데이트됩니다.
        """
        from sqlalchemy import delete as sql_delete

        # 삭제할 문서 조회
        document = await self.get_by_id(criteria_id)
        if not document:
            return None

        # 활성 문서인 경우 active_criteria 테이블 정리
        if document.status == "active":
            await self.db.execute(
                update(ActiveCriteria)
                .where(ActiveCriteria.criteria_document_id == criteria_id)
                .values(
                    criteria_document_id=None,
                    activated_at=None,
                    activated_by=None,
                )
            )

        # 문서 삭제
        await self.db.execute(
            sql_delete(CriteriaDocument).where(
                CriteriaDocument.id == criteria_id
            )
        )

        await self.db.flush()
        return document

    async def delete_all(self) -> int:
        """
        모든 평가 기준 문서 삭제

        Returns:
            삭제된 문서 개수

        Note:
            active_criteria 테이블도 초기화됩니다.
        """
        from sqlalchemy import delete as sql_delete

        # 전체 개수 조회
        count_result = await self.db.execute(
            select(func.count(CriteriaDocument.id))
        )
        total = count_result.scalar() or 0

        if total == 0:
            return 0

        # active_criteria 테이블 초기화
        await self.db.execute(
            update(ActiveCriteria)
            .where(ActiveCriteria.id == 1)
            .values(
                criteria_document_id=None,
                activated_at=None,
                activated_by=None,
            )
        )

        # 모든 문서 삭제
        await self.db.execute(sql_delete(CriteriaDocument))

        await self.db.flush()
        return total
