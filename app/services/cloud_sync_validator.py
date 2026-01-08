"""
클라우드 동기화 검증 서비스
API Key 변경 시 로컬 DB와 클라우드 상태 불일치 감지
"""
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SyncValidationResult:
    """동기화 검증 결과"""
    is_synced: bool
    cloud_store_exists: bool
    cloud_doc_count: int
    local_active_count: int
    warning_message: Optional[str] = None
    needs_resync: bool = False


class CloudSyncValidator:
    """클라우드 동기화 상태 검증 서비스"""

    def __init__(self):
        """초기화"""
        self._client = None

    @property
    def client(self):
        """Lazy 클라이언트 초기화"""
        if self._client is None:
            from google import genai
            self._client = genai.Client(
                api_key=settings.GOOGLE_API_KEY,
                http_options={'api_version': 'v1beta'}
            )
        return self._client

    async def validate_rubricstore_sync(
        self,
        db: AsyncSession
    ) -> SyncValidationResult:
        """
        rubricstore 동기화 상태 검증
        
        Args:
            db: 데이터베이스 세션
            
        Returns:
            SyncValidationResult: 검증 결과
        """
        try:
            # 1. 클라우드에서 rubricstore 찾기
            cloud_store = None
            cloud_doc_count = 0
            
            for store in self.client.file_search_stores.list():
                display_name = store.display_name or ""
                normalized_name = (
                    display_name.lower()
                    .replace("-", "")
                    .replace("_", "")
                )
                if "rubricstore" in normalized_name:
                    cloud_store = store
                    logger.info(
                        f"클라우드 rubricstore 발견: "
                        f"{display_name} ({store.name})"
                    )
                    break

            if cloud_store and cloud_store.name:
                try:
                    docs = list(
                        self.client.file_search_stores.documents.list(
                            parent=cloud_store.name
                        )
                    )
                    cloud_doc_count = len(docs)
                    logger.info(
                        f"클라우드 rubricstore 문서 수: {cloud_doc_count}"
                    )
                except Exception as e:
                    logger.warning(f"클라우드 문서 목록 조회 실패: {e}")
                    cloud_doc_count = 0

            # 3. 로컬 DB에서 활성 평가기준 수 확인
            from app.models.criteria import Criteria
            result = await db.execute(
                select(Criteria).where(Criteria.status == "active")
            )
            local_active = result.scalars().all()
            local_active_count = len(local_active)
            
            logger.info(
                f"로컬 DB 활성 평가기준 수: {local_active_count}"
            )

            # 4. 불일치 판단
            if not cloud_store:
                # 클라우드에 store가 없음
                if local_active_count > 0:
                    return SyncValidationResult(
                        is_synced=False,
                        cloud_store_exists=False,
                        cloud_doc_count=0,
                        local_active_count=local_active_count,
                        warning_message=(
                            f"클라우드에 rubricstore가 없습니다. "
                            f"로컬에 {local_active_count}개의 활성 평가기준이 있지만 "
                            f"클라우드와 동기화되지 않았습니다. "
                            f"'활성화 확정' 버튼을 눌러 동기화하세요."
                        ),
                        needs_resync=True
                    )
                else:
                    # 둘 다 비어있음 - 정상
                    return SyncValidationResult(
                        is_synced=True,
                        cloud_store_exists=False,
                        cloud_doc_count=0,
                        local_active_count=0
                    )

            # 5. store는 있지만 문서 수 불일치
            if cloud_doc_count != local_active_count:
                return SyncValidationResult(
                    is_synced=False,
                    cloud_store_exists=True,
                    cloud_doc_count=cloud_doc_count,
                    local_active_count=local_active_count,
                    warning_message=(
                        f"클라우드와 로컬 DB가 동기화되지 않았습니다. "
                        f"클라우드: {cloud_doc_count}개, "
                        f"로컬 DB: {local_active_count}개. "
                        f"API Key가 변경되었거나 동기화가 필요합니다. "
                        f"'활성화 확정' 버튼을 눌러 재동기화하세요."
                    ),
                    needs_resync=True
                )

            if local_active_count > 0 and cloud_store and cloud_store.name:
                invalid_refs = []
                for criteria in local_active:
                    doc_id = criteria.document_id
                    if doc_id and cloud_store.name not in doc_id:
                        invalid_refs.append(criteria.title)
                
                if invalid_refs:
                    return SyncValidationResult(
                        is_synced=False,
                        cloud_store_exists=True,
                        cloud_doc_count=cloud_doc_count,
                        local_active_count=local_active_count,
                        warning_message=(
                            f"로컬 DB의 평가기준이 이전 API Key의 "
                            f"클라우드를 참조하고 있습니다. "
                            f"({', '.join(invalid_refs[:3])}...) "
                            f"'활성화 확정' 버튼을 눌러 재동기화하세요."
                        ),
                        needs_resync=True
                    )

            # 7. 모든 검증 통과
            return SyncValidationResult(
                is_synced=True,
                cloud_store_exists=True,
                cloud_doc_count=cloud_doc_count,
                local_active_count=local_active_count
            )

        except Exception as e:
            logger.error(
                f"동기화 검증 실패: {e}",
                exc_info=True
            )
            return SyncValidationResult(
                is_synced=False,
                cloud_store_exists=False,
                cloud_doc_count=0,
                local_active_count=0,
                warning_message=(
                    f"클라우드 연결 오류: {str(e)}. "
                    f"API Key 설정을 확인하세요."
                ),
                needs_resync=True
            )

    async def get_cloud_stores_info(self) -> Dict[str, Any]:
        """
        현재 API Key의 모든 클라우드 store 정보 조회
        
        Returns:
            store 정보 딕셔너리
        """
        try:
            stores = []
            for store in self.client.file_search_stores.list():
                store_name = store.name or ""
                try:
                    if store_name:
                        docs = list(
                            self.client.file_search_stores.documents.list(
                                parent=store_name
                            )
                        )
                        doc_count = len(docs)
                    else:
                        doc_count = -1
                except Exception:
                    doc_count = -1
                
                stores.append({
                    "display_name": store.display_name or "unknown",
                    "store_id": store_name,
                    "document_count": doc_count
                })
            
            return {
                "success": True,
                "stores": stores,
                "total_count": len(stores)
            }
        except Exception as e:
            logger.error(f"클라우드 store 정보 조회 실패: {e}")
            return {
                "success": False,
                "error": str(e),
                "stores": [],
                "total_count": 0
            }
