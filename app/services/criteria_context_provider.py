"""
평가 기준 컨텍스트 제공자
앱 전역에서 활성 기준 문서의 vector_store_id를 관리
"""
from typing import Optional
import logging

from app.db import get_db
from app.repositories.criteria_repository import CriteriaRepository

logger = logging.getLogger(__name__)


class CriteriaContextProvider:
    """
    활성 평가 기준 컨텍스트 싱글톤 관리자

    앱 시작 시 활성 기준 문서를 로드하고,
    메모리 캐시로 vector_store_id를 제공합니다.
    """

    def __init__(self):
        """Provider 초기화"""
        self._active_vector_store_id: Optional[str] = None
        self._active_criteria_id: Optional[int] = None
        self._is_initialized: bool = False

    async def initialize(self) -> None:
        """
        앱 시작 시 활성 기준 문서 로드

        FastAPI startup 이벤트에서 호출됩니다.
        """
        try:
            await self.reload_active()
            self._is_initialized = True
            logger.info(
                f"CriteriaContextProvider initialized. "
                f"Active criteria: {self._active_criteria_id}"
            )
        except Exception as e:
            logger.error(
                f"Failed to initialize "
                f"CriteriaContextProvider: {e}"
            )
            # 초기화 실패는 치명적이지 않음 (나중에 활성화 가능)
            self._is_initialized = True

    async def reload_active(self) -> None:
        """
        활성 기준 문서 재로드

        활성화 변경 시 호출하여 캐시를 갱신합니다.
        """
        async for db in get_db():
            try:
                repo = CriteriaRepository(db)
                active_doc = await repo.get_active()

                if active_doc:
                    self._active_vector_store_id = (
                        active_doc.vector_store_id
                    )
                    self._active_criteria_id = active_doc.id
                    logger.info(
                        f"Reloaded active criteria: "
                        f"{self._active_criteria_id}"
                    )
                else:
                    self._active_vector_store_id = None
                    self._active_criteria_id = None
                    logger.warning("No active criteria found")
            finally:
                await db.close()
                break  # get_db는 제너레이터이므로 첫 항목만 사용

    def get_active_vector_store_id(self) -> Optional[str]:
        """
        현재 활성 기준의 vector_store_id 반환

        Returns:
            활성 vector_store_id 또는 None

        Raises:
            RuntimeError: Provider가 초기화되지 않았을 때
        """
        if not self._is_initialized:
            raise RuntimeError(
                "CriteriaContextProvider not initialized. "
                "Call initialize() first."
            )
        return self._active_vector_store_id

    def get_active_criteria_id(self) -> Optional[int]:
        """
        현재 활성 기준 문서 ID 반환

        Returns:
            활성 criteria_id 또는 None
        """
        if not self._is_initialized:
            raise RuntimeError(
                "CriteriaContextProvider not initialized"
            )
        return self._active_criteria_id

    def has_active_criteria(self) -> bool:
        """
        활성 기준 존재 여부 확인

        Returns:
            활성 기준이 있으면 True
        """
        return self._active_vector_store_id is not None


# 모듈 레벨 싱글톤 인스턴스
criteria_context_provider = CriteriaContextProvider()
