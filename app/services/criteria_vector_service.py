"""
평가기준 Vector DB 관리 서비스
Gemini File Search API를 사용한 평가기준 임베딩 저장 및 검색
"""
import logging
from typing import Dict, Any, Optional, List
from app.services.file_search_service import FileSearchService
from app.config import settings

logger = logging.getLogger(__name__)


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
        display_name: str,
        metadata: Optional[Dict[str, Any]] = None,
        recreate_store: bool = True,
    ) -> Dict[str, str]:
        """
        평가기준 파일을 Vector DB에 업로드
        (기본: 기존 평가기준 자동 삭제 후 업로드, 옵션: 재생성 생략)

        Args:
            file_path: 평가기준 파일 경로
            display_name: 표시 이름
            metadata: 추가 메타데이터 (선택)
            recreate_store: 업로드 전에 Store를 재생성할지 여부
                - True: 기존 평가기준을 모두 지우고 업로드 (기본)
                - False: 이미 준비된 Store를 그대로 사용 (다중 업로드 시 사용)

        Returns:
            document_id와 store_id 딕셔너리
        """
        try:
            logger.info(
                f"평가기준 업로드 프로세스 시작: {display_name}"
            )

            # 1. 기존 평가기준 Store 재생성 (필요 시)
            if recreate_store:
                logger.debug("단계 1/3: Store 재생성")
                await self._recreate_criteria_store()
                logger.debug("단계 1/3: Store 재생성 완료")
            else:
                logger.debug("단계 1/3: 기존 Store 유지 (재생성 생략)")

            # 2. 메타데이터 설정
            logger.debug("단계 2/3: 메타데이터 설정")
            upload_metadata = metadata or {}
            upload_metadata["type"] = "criteria"
            logger.debug(
                f"메타데이터: {upload_metadata}"
            )

            # 3. 새 평가기준 업로드
            logger.debug("단계 3/3: 문서 업로드 시작")
            result = await self.file_search_service.upload_document(
                file_path=file_path,
                display_name=display_name,
                metadata=upload_metadata,
                store_type="rubric",
            )
            logger.debug("단계 3/3: 문서 업로드 완료")

            logger.info(
                f"평가기준 업로드 완료: {display_name}\n"
                f"  - Document ID: {result['document_id']}\n"
                f"  - Store ID: {result['store_id']}"
            )

            return result
        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                f"평가기준 업로드 실패 - "
                f"유형: {error_type}, "
                f"메시지: {str(e)}",
                exc_info=True
            )
            raise

    async def delete_criteria(
        self,
        document_id: str
    ) -> bool:
        """
        특정 평가기준 삭제 (Store 재생성 방식)

        Note:
            Gemini File Search API는 개별 document 삭제 불가
            → Store 재생성으로 모든 문서 삭제

        Args:
            document_id: 삭제할 문서 ID (사용 안 함)

        Returns:
            삭제 성공 여부
        """
        try:
            await self._recreate_criteria_store()
            logger.info(
                f"평가기준 삭제 완료 (Store 재생성): {document_id}"
            )
            return True
        except Exception as e:
            logger.error(f"평가기준 삭제 실패: {str(e)}")
            raise

    async def delete_all_criteria(self) -> bool:
        """
        모든 평가기준 삭제 (Store 재생성)

        Returns:
            삭제 성공 여부
        """
        try:
            await self._recreate_criteria_store()
            logger.info("모든 평가기준 삭제 완료 (Store 재생성)")
            return True
        except Exception as e:
            logger.error(f"모든 평가기준 삭제 실패: {str(e)}")
            raise

    async def _recreate_criteria_store(self) -> None:
        """
        평가기준 Store 재생성
        (기존 Store 삭제 후 새로 생성)
        """
        try:
            client = self.file_search_service.client

            logger.info("평가기준 Store 재생성 시작")

            # 1. 기존 Store 찾기 및 삭제
            logger.debug("기존 Store 검색 중...")
            stores_found = 0
            for store in client.file_search_stores.list():
                stores_found += 1
                if store.display_name == self.store_name:
                    logger.info(
                        f"기존 Store 발견 - 삭제 진행: {self.store_name} "
                        f"(ID: {store.name})"
                    )
                    
                    # force=True로 비어있지 않은 Store도 삭제 가능
                    client.file_search_stores.delete(
                        name=store.name,
                        config={'force': True}
                    )
                    logger.info("기존 Store 삭제 완료 (force=True)")
                    break
            else:
                logger.info(
                    f"기존 Store 없음 (전체 {stores_found}개 Store 확인)"
                )

            # 2. 새 Store 생성
            logger.debug(f"새 Store 생성 중: {self.store_name}")
            new_store = client.file_search_stores.create(
                config={'display_name': self.store_name}
            )
            logger.info(
                f"새 Store 생성 완료: {self.store_name} "
                f"(ID: {new_store.name})"
            )
        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                f"Store 재생성 실패 - "
                f"유형: {error_type}, "
                f"메시지: {str(e)}",
                exc_info=True
            )
            raise

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

            # metadata_filter 설정
            # 올바른 구문: 'type=\"criteria\"'
            metadata_filter = 'type="criteria"'

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

    async def list_criteria_documents(self) -> List[Dict[str, str]]:
        """
        현재 저장된 평가기준 문서 목록 조회

        Returns:
            문서 정보 리스트
            - document_id: 문서 ID
            - display_name: 표시 이름
        """
        try:
            client = self.file_search_service.client
            store = None

            # Store 찾기
            for s in client.file_search_stores.list():
                if s.display_name == self.store_name:
                    store = s
                    break

            if not store:
                logger.warning(
                    f"평가기준 Store를 찾을 수 없습니다: "
                    f"{self.store_name}"
                )
                return []

            # Store 내 문서 목록 조회
            # 수정: 올바른 API는 documents.list(parent=...)
            documents = []
            for doc in client.file_search_stores.documents.list(
                parent=store.name
            ):
                documents.append(
                    {
                        "document_id": doc.name,
                        "display_name": doc.display_name
                        if hasattr(doc, "display_name")
                        else "Unknown",
                    }
                )

            logger.info(
                f"평가기준 문서 목록 조회: {len(documents)}개"
            )
            return documents
        except Exception as e:
            logger.error(f"문서 목록 조회 실패: {str(e)}")
            raise

    async def list_document_ids(self) -> List[str]:
        """클라우드에 있는 문서 ID 목록만 반환."""
        docs = await self.list_criteria_documents()
        return [d["document_id"] for d in docs]
