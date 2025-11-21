"""
평가 기준 감사 로그 서비스
관리자 작업 추적 및 감사
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.criteria import CriteriaAuditLog

logger = logging.getLogger(__name__)


class CriteriaAuditService:
    """평가 기준 감사 로그 서비스"""

    # 액션 타입 상수
    ACTION_UPLOAD = "upload"
    ACTION_ACTIVATE = "activate"
    ACTION_DEACTIVATE = "deactivate"
    ACTION_SEARCH = "search"
    ACTION_DELETE = "delete"
    ACTION_DELETE_ALL = "delete_all"

    def __init__(self, db: AsyncSession):
        """
        초기화

        Args:
            db: 데이터베이스 세션
        """
        self.db = db

    async def log_upload(
        self,
        criteria_id: int,
        actor_id: int,
        file_name: str,
        file_size: int,
        vector_store_id: str,
    ) -> None:
        """
        업로드 이벤트 로깅

        Args:
            criteria_id: 기준 문서 ID
            actor_id: 작업자 ID
            file_name: 파일명
            file_size: 파일 크기
            vector_store_id: 벡터 스토어 ID
        """
        detail = (
            f"파일명: {file_name}, "
            f"크기: {file_size} bytes, "
            f"vector_store: {vector_store_id}"
        )

        await self._create_log(
            action=self.ACTION_UPLOAD,
            criteria_id=criteria_id,
            actor_id=actor_id,
            detail=detail,
        )

        logger.info(
            f"[AUDIT] 업로드: criteria_id={criteria_id}, "
            f"actor={actor_id}"
        )

    async def log_activate(
        self,
        criteria_id: int,
        actor_id: int,
        title: str,
        previous_active_id: Optional[int] = None,
    ) -> None:
        """
        활성화 이벤트 로깅

        Args:
            criteria_id: 활성화된 기준 문서 ID
            actor_id: 작업자 ID
            title: 문서 제목
            previous_active_id: 이전 활성 문서 ID
        """
        detail = f"문서: {title}"
        if previous_active_id:
            detail += f", 이전 활성: {previous_active_id}"

        await self._create_log(
            action=self.ACTION_ACTIVATE,
            criteria_id=criteria_id,
            actor_id=actor_id,
            detail=detail,
        )

        logger.info(
            f"[AUDIT] 활성화: criteria_id={criteria_id}, "
            f"actor={actor_id}"
        )

    async def log_deactivate(
        self,
        criteria_id: int,
        actor_id: int,
        title: str,
    ) -> None:
        """
        비활성화 이벤트 로깅

        Args:
            criteria_id: 비활성화된 기준 문서 ID
            actor_id: 작업자 ID
            title: 문서 제목
        """
        detail = f"문서: {title}"

        await self._create_log(
            action=self.ACTION_DEACTIVATE,
            criteria_id=criteria_id,
            actor_id=actor_id,
            detail=detail,
        )

        logger.info(
            f"[AUDIT] 비활성화: criteria_id={criteria_id}, "
            f"actor={actor_id}"
        )

    async def log_search(
        self,
        criteria_id: int,
        query: str,
        result_count: int,
        actor_id: Optional[int] = None,
    ) -> None:
        """
        검색 이벤트 로깅 (선택)

        Args:
            criteria_id: 검색에 사용된 기준 문서 ID
            query: 검색 쿼리
            result_count: 결과 개수
            actor_id: 작업자 ID (선택)
        """
        # 쿼리가 너무 길면 잘라내기
        truncated_query = (
            query[:100] + "..." if len(query) > 100 else query
        )

        detail = (
            f"쿼리: {truncated_query}, "
            f"결과: {result_count}개"
        )

        await self._create_log(
            action=self.ACTION_SEARCH,
            criteria_id=criteria_id,
            actor_id=actor_id,
            detail=detail,
        )

        logger.debug(
            f"[AUDIT] 검색: criteria_id={criteria_id}, "
            f"results={result_count}"
        )

    async def log_delete(
        self,
        criteria_id: int,
        actor_id: int,
        title: str,
    ) -> None:
        """
        삭제 이벤트 로깅

        Args:
            criteria_id: 삭제된 기준 문서 ID
            actor_id: 작업자 ID
            title: 문서 제목
        """
        detail = f"문서 삭제: {title}"

        await self._create_log(
            action=self.ACTION_DELETE,
            criteria_id=criteria_id,
            actor_id=actor_id,
            detail=detail,
        )

        logger.info(
            f"[AUDIT] 삭제: criteria_id={criteria_id}, "
            f"actor={actor_id}"
        )

    async def log_delete_all(
        self,
        actor_id: int,
        deleted_count: int,
    ) -> None:
        """
        전체 삭제 이벤트 로깅

        Args:
            actor_id: 작업자 ID
            deleted_count: 삭제된 문서 개수
        """
        detail = f"전체 삭제: {deleted_count}개 문서"

        await self._create_log(
            action=self.ACTION_DELETE_ALL,
            criteria_id=None,
            actor_id=actor_id,
            detail=detail,
        )

        logger.info(
            f"[AUDIT] 전체 삭제: count={deleted_count}, "
            f"actor={actor_id}"
        )

    async def log_action(
        self,
        action: str,
        actor_id: int,
        criteria_id: Optional[int] = None,
        detail: Optional[str] = None,
    ) -> None:
        """
        일반 액션 로깅 (범용)

        Args:
            action: 액션 타입
            actor_id: 작업자 ID
            criteria_id: 기준 문서 ID (선택)
            detail: 상세 정보 (선택)
        """
        await self._create_log(
            action=action,
            criteria_id=criteria_id,
            actor_id=actor_id,
            detail=detail,
        )

        logger.info(
            f"[AUDIT] {action}: criteria_id={criteria_id}, "
            f"actor={actor_id}"
        )

    async def _create_log(
        self,
        action: str,
        criteria_id: Optional[int] = None,
        actor_id: Optional[int] = None,
        detail: Optional[str] = None,
    ) -> CriteriaAuditLog:
        """
        감사 로그 생성 (내부 메서드)

        Args:
            action: 액션 타입
            criteria_id: 기준 문서 ID
            actor_id: 작업자 ID
            detail: 상세 정보

        Returns:
            생성된 감사 로그
        """
        log = CriteriaAuditLog(
            action=action,
            criteria_document_id=criteria_id,
            actor_id=actor_id,
            detail=detail,
        )

        self.db.add(log)
        # commit은 호출자가 수행

        return log


# ===== 의존성 주입 헬퍼 =====


def get_audit_service(
    db: AsyncSession,
) -> CriteriaAuditService:
    """
    CriteriaAuditService 의존성 주입

    Args:
        db: 데이터베이스 세션

    Returns:
        CriteriaAuditService 인스턴스
    """
    return CriteriaAuditService(db)
