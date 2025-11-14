"""
Google File Search 서비스
문서 업로드, 인덱싱, RAG 쿼리
"""
import asyncio
import logging
from typing import Optional, Dict, Any
from google import genai
from google.genai import types
from app.config import settings

logger = logging.getLogger(__name__)


class FileSearchService:
    """File Search 서비스 클래스"""

    _client = None

    @classmethod
    def get_client(cls):
        """싱글톤 Client 인스턴스 반환"""
        if cls._client is None:
            cls._client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        return cls._client

    def __init__(self):
        """
        FileSearchService 초기화
        - Google API 키 검증
        - 클라이언트 초기화
        """
        if not settings.GOOGLE_API_KEY:
            raise ValueError(
                "GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다"
            )

        self.client = self.get_client()
        self.main_store_name = settings.FS_MAIN_STORE_NAME
        self.rubric_store_name = settings.FS_RUBRIC_STORE_NAME

    async def initialize_stores(self) -> Dict[str, str]:
        """
        File Search 스토어 초기화

        Returns:
            스토어 ID 딕셔너리
        """
        try:
            # 메인 스토어 생성 또는 가져오기
            main_store = self._get_or_create_store(
                self.main_store_name
            )
            rubric_store = self._get_or_create_store(
                self.rubric_store_name
            )

            logger.info(
                f"File Search 스토어 초기화 완료: "
                f"main={main_store.name}, "
                f"rubric={rubric_store.name}"
            )

            return {
                "main": main_store.name,
                "rubric": rubric_store.name,
            }
        except Exception as e:
            logger.error(f"스토어 초기화 실패: {str(e)}")
            raise

    def _get_or_create_store(self, store_name: str):
        """FileSearchStore 가져오기 또는 생성"""
        try:
            # 기존 스토어 찾기
            for store in self.client.file_search_stores.list():
                if store.display_name == store_name:
                    logger.info(f"기존 스토어 발견: {store_name} (ID: {store.name})")
                    return store

            # 없으면 새로 생성
            store = self.client.file_search_stores.create(
                config={'display_name': store_name}
            )
            logger.info(f"새 스토어 생성: {store_name} (ID: {store.name})")
            return store
        except Exception as e:
            logger.error(f"스토어 처리 실패: {str(e)}")
            raise

    async def upload_document(
        self,
        file_path: str,
        display_name: str,
        metadata: Dict[str, Any],
        store_type: str = "main",
    ) -> Dict[str, str]:
        """
        문서를 File Search Store에 업로드 (최신 API)

        Args:
            file_path: 파일 경로
            display_name: 표시 이름
            metadata: 메타데이터 (user_id, random_key 등)
            store_type: 스토어 타입 (main/rubric)

        Returns:
            document_id와 store_id 포함 딕셔너리
        """
        try:
            # 스토어 선택
            store_name = (
                self.main_store_name
                if store_type == "main"
                else self.rubric_store_name
            )
            store = self._get_or_create_store(store_name)

            # Custom metadata 구조 변환
            custom_metadata = []
            for key, value in metadata.items():
                if isinstance(value, (int, float)):
                    custom_metadata.append({
                        "key": key,
                        "numeric_value": value
                    })
                else:
                    custom_metadata.append({
                        "key": key,
                        "string_value": str(value)
                    })

            # 직접 업로드 및 청킹 설정
            operation = self.client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store.name,
                file=file_path,
                config={
                    'chunking_config': {
                        'white_space_config': {
                            'max_tokens_per_chunk': settings.FS_CHUNKING_MAX_TOKENS,
                            'max_overlap_tokens': settings.FS_CHUNKING_OVERLAP_TOKENS
                        }
                    },
                    'custom_metadata': custom_metadata
                }
            )

            # Polling 루프 (타임아웃 설정값 사용)
            max_wait = settings.FS_UPLOAD_TIMEOUT
            elapsed = 0
            poll_interval = settings.FS_POLL_INTERVAL

            logger.info(f"파일 업로드 시작: {display_name}, 인덱싱 대기 중...")

            while not operation.done and elapsed < max_wait:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                try:
                    operation = self.client.operations.get(operation)
                    logger.debug(f"인덱싱 진행 중... (경과: {elapsed}초)")
                except Exception as e:
                    logger.info(f"Operation 빠른 완료 감지: {str(e)}")
                    break

            if not operation.done:
                raise TimeoutError(
                    f"파일 업로드 타임아웃 ({max_wait}초 초과): {display_name}"
                )

            # API 응답 구조: document_name, parent 속성 사용
            document_id = operation.response.document_name
            store_id = operation.response.parent

            logger.info(
                f"문서 업로드 및 인덱싱 완료: {display_name}\n"
                f"  - Document ID: {document_id}\n"
                f"  - Store ID: {store_id}\n"
                f"  - 소요 시간: {elapsed}초"
            )

            return {
                "document_id": document_id,
                "store_id": store_id,
            }
        except Exception as e:
            logger.error(f"문서 업로드 실패: {str(e)}")
            raise

    async def delete_document(self, file_id: str) -> None:
        """
        File Search Store에서 문서 삭제

        Args:
            file_id: 문서 전체 경로 (예: fileSearchStores/xxx/documents/yyy)
        """
        try:
            # Google API: files.delete 또는 file_search_stores의 documents 삭제
            # file_id는 이미 전체 경로 형식
            self.client.files.delete(name=file_id)
            logger.info(f"문서 삭제 완료: {file_id}")
        except Exception as e:
            logger.warning(f"문서 삭제 실패 (이미 삭제되었을 수 있음): {str(e)}")
