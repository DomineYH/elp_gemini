"""
평가기준 Vector DB 관리 서비스
Gemini File Search API를 사용한 평가기준 임베딩 저장 및 검색
"""
import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.file_search_service import (
    _MANIFEST_PAYLOAD_CHUNK_SIZE,
    FileSearchService,
)

logger = logging.getLogger(__name__)


def _string_list_metadata(key: str, value: str) -> dict:
    chunks = [
        value[i:i + _MANIFEST_PAYLOAD_CHUNK_SIZE]
        for i in range(0, len(value), _MANIFEST_PAYLOAD_CHUNK_SIZE)
    ] or [""]
    return {"key": key, "string_list_value": {"values": chunks}}


class CriteriaVectorService:
    """평가기준 Vector DB 관리 서비스"""

    def __init__(self):
        """
        서비스 초기화
        - FileSearchService 인스턴스 생성
        - Rubric Store 이름 설정
        """
        self.file_search_service = FileSearchService()
        self.store_name = settings.FS_RUBRIC_STORE_NAME

    async def upload_criteria(
        self,
        file_path: str,
        title: str,
        stable_id: str,
    ) -> Dict[str, str]:
        """
        평가기준 1개를 rubric-store에 업로드 (store 재생성 없이).

        custom_metadata:
          type = "criteria"
          stable_id = <ULID>
          original_title_b64 = base64(UTF-8 title)
          created_at = ISO-8601 UTC
        """
        import base64
        from datetime import datetime, timezone

        original_title_b64 = base64.b64encode(
            title.encode("utf-8")
        ).decode("ascii")
        created_at = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )

        metadata = [
            {"key": "type", "string_value": "criteria"},
            {"key": "stable_id", "string_value": stable_id},
            _string_list_metadata("original_title_b64", original_title_b64),
            _string_list_metadata("created_at", created_at),
        ]
        result = await self.file_search_service.upload_document(
            file_path=file_path,
            display_name=title,
            metadata=metadata,
            store_type="rubric",
        )
        logger.info(
            "평가기준 업로드 완료: "
            f"stable_id={stable_id} document_id={result['document_id']}"
        )
        return result

    async def delete_criteria(self, document_id: str) -> bool:
        """document_id로 식별되는 평가기준 1개를 삭제. store 재생성 없음.

        Gemini File Search Document는 chunk를 포함한 상태에서 삭제하려면
        ``force=True`` 가 필요하다. 미전달 시 ``400 FAILED_PRECONDITION
        Cannot delete non-empty Document`` 가 발생한다 (issue #68).
        """
        if not document_id:
            raise ValueError("document_id가 비어있습니다")
        self.file_search_service.client.file_search_stores.documents.delete(
            name=document_id,
            config={"force": True},
        )
        logger.info(f"평가기준 삭제 완료: {document_id}")
        return True

    async def search_criteria(
        self,
        query: str,
        model: str = None,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """
        평가기준에서 관련 내용 검색

        Args:
            query: 검색 쿼리
            model: 사용할 모델 (None이면 settings.GEMINI_QNA_MODEL 사용)
            temperature: 생성 온도

        Returns:
            response_text: 생성된 답변
            citations: 인용 정보
            sources_count: 참조 소스 개수
        """
        try:
            if model is None:
                model = settings.GEMINI_QNA_MODEL

            client = self.file_search_service.client
            store = None

            for s in client.file_search_stores.list():
                if s.display_name == self.store_name:
                    store = s
                    break

            if not store:
                raise ValueError(
                    f"평가기준 Store를 찾을 수 없습니다: "
                    f"{self.store_name}"
                )

            metadata_filter = await self.active_stable_id_filter(
                client=client,
                store_display_name=self.store_name,
            )
            if not metadata_filter:
                logger.info("활성 평가기준 없음 — 검색 생략")
                return {
                    "response_text": "",
                    "citations": [],
                    "sources_count": 0,
                }

            # 검색 수행
            result = await self.file_search_service.search_in_store(
                query=query,
                store_name=store.name,
                model=model,
                metadata_filter=metadata_filter,
                temperature=temperature,
            )

            logger.info(
                f"평가기준 검색 완료: {query[:50]}..., "
                f"sources={result['sources_count']}"
            )

            return result
        except Exception as e:
            logger.error(f"평가기준 검색 실패: {str(e)}")
            raise

    @staticmethod
    async def active_stable_id_filter(
        client,
        store_display_name: Optional[str] = None,
    ) -> Optional[str]:
        """현재 active 평가기준들에 대한 File Search metadata_filter 반환.

        - 0개: None (평가기준 미설정 안내 트리거)
        - 1개: stable_id="X"
        - N개: (stable_id="A" OR stable_id="B" ...) — AIP-160 OR 결합
        """
        active_stable_ids = await CriteriaVectorService._get_active_stable_ids(
            client=client,
            store_display_name=(
                store_display_name or settings.FS_RUBRIC_STORE_NAME
            ),
        )
        if not active_stable_ids:
            return None

        def _eq(sid: str) -> str:
            escaped = sid.replace("\\", "\\\\").replace('"', '\\"')
            return f'stable_id="{escaped}"'

        if len(active_stable_ids) == 1:
            return _eq(active_stable_ids[0])

        joined = " OR ".join(_eq(sid) for sid in active_stable_ids)
        return f"({joined})"

    @staticmethod
    async def _get_active_stable_ids(
        client,
        store_display_name: Optional[str] = None,
    ) -> list[str]:
        """alias_map에서 active stable_id들을 정렬해 반환.

        정렬: activated_at desc, stable_id desc.
        """
        from app.services.criteria_alias_map_service import (
            CriteriaAliasMapService,
        )

        alias_svc = CriteriaAliasMapService(
            client=client,
            store_display_name=(
                store_display_name or settings.FS_RUBRIC_STORE_NAME
            ),
        )
        fetched = await alias_svc.fetch()
        if not fetched:
            return []

        _, alias_map = fetched
        from app.services.criteria_reconciliation_service import (
            is_legacy_surrogate_stable_id,
        )

        active_entries = [
            (stable_id, entry)
            for stable_id, entry in alias_map.entries.items()
            if (
                entry.status == "active"
                and not is_legacy_surrogate_stable_id(stable_id)
            )
        ]
        if not active_entries:
            return []

        active_entries.sort(
            key=lambda item: (item[1].activated_at or "", item[0]),
            reverse=True,
        )
        return [sid for sid, _ in active_entries]

    async def list_criteria_documents(self) -> List[Dict[str, Any]]:
        """
        rubric-store 모든 문서를 메타데이터와 함께 반환.

        반환 형식:
          [{
              document_id,
              display_name,
              custom_metadata_kv: {key: (string_value, [string_list_values])},
          }]
        """
        from app.services.criteria_alias_map_service import _read_metadata_kv

        client = self.file_search_service.client
        store = next(
            (
                s
                for s in client.file_search_stores.list()
                if s.display_name == self.store_name
            ),
            None,
        )
        if not store:
            logger.warning(f"rubric-store 미존재: {self.store_name}")
            return []

        documents = []
        for doc in client.file_search_stores.documents.list(parent=store.name):
            documents.append(
                {
                    "document_id": doc.name,
                    "display_name": getattr(doc, "display_name", None),
                    "custom_metadata_kv": _read_metadata_kv(
                        getattr(doc, "custom_metadata", None)
                    ),
                }
            )
        return documents

    async def list_document_ids(self) -> List[str]:
        """클라우드에 있는 문서 ID 목록만 반환."""
        docs = await self.list_criteria_documents()
        return [d["document_id"] for d in docs]
