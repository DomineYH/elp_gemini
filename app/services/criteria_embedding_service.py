"""
평가 기준 임베딩 서비스
Google File Search Tool을 이용한 기준 문서 업로드 및 임베딩
"""
import asyncio
import logging
import time
from typing import Dict, Any, Tuple
from google import genai
from google.genai import types
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from app.config import settings

logger = logging.getLogger(__name__)

# 재시도 가능한 예외 정의
# ConnectionError: 네트워크 일시 장애
# 향후 Google API 특정 예외 추가 예정
RETRIABLE_EXCEPTIONS = (ConnectionError,)


class CriteriaEmbeddingService:
    """평가 기준 임베딩 서비스"""

    _client = None

    @classmethod
    def get_client(cls):
        """싱글톤 Client 인스턴스 반환"""
        if cls._client is None:
            cls._client = genai.Client(
                api_key=settings.GOOGLE_API_KEY
            )
        return cls._client

    def __init__(self):
        """
        CriteriaEmbeddingService 초기화

        Raises:
            ValueError: GOOGLE_API_KEY가 설정되지 않은 경우
        """
        if not settings.GOOGLE_API_KEY:
            raise ValueError(
                "GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다"
            )

        self.client = self.get_client()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(RETRIABLE_EXCEPTIONS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,  # 원래 예외 재발생
    )
    def _create_unique_store(self, title: str):
        """
        문서별 고유 Vector Store 생성 (재시도: 최대 3회)

        Args:
            title: 문서 제목 (로깅용)

        Returns:
            FileSearchStore 객체

        Raises:
            Exception: 스토어 생성 실패 시
        """
        try:
            import uuid
            import time

            # 고유한 스토어 이름 생성
            # 형식: criteria-{timestamp}-{uuid}
            timestamp = int(time.time() * 1000)
            unique_id = str(uuid.uuid4())[:8]
            store_name = f"criteria-{timestamp}-{unique_id}"

            # 스토어 설정 구성
            store_config = {"display_name": store_name}

            # Vector Store 생성
            store = self.client.file_search_stores.create(
                config=store_config
            )

            logger.info(
                f"새 Criteria 스토어 생성: {title}\n"
                f"  - Store Name: {store_name}\n"
                f"  - Store ID: {store.name}"
            )

            return store

        except Exception as e:
            logger.error(
                f"Criteria 스토어 생성 실패 ({title}): {str(e)}"
            )
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(RETRIABLE_EXCEPTIONS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,  # 원래 예외 재발생
    )
    async def upload_and_embed(
        self,
        file_path: str,
        title: str,
        metadata: Dict[str, Any] = None,
    ) -> Tuple[str, str]:
        """
        기준 문서 업로드 및 임베딩 생성 (재시도: 최대 3회)

        Args:
            file_path: PDF 파일 경로
            title: 문서 제목
            metadata: 추가 메타데이터 (선택)

        Returns:
            Tuple[vector_store_id, document_id]
            - vector_store_id: Google File Search Store ID
            - document_id: Google File Search Document ID

        Raises:
            TimeoutError: 업로드 타임아웃
            Exception: 업로드 실패
        """
        # 성능 측정 시작
        total_start = time.time()

        store = None  # 정리를 위한 초기화
        try:
            # 스토어 생성 시간 측정
            store_start = time.time()
            store = self._create_unique_store(title)
            store_time = time.time() - store_start

            # Custom metadata 구조 변환
            custom_metadata = []
            if metadata:
                for key, value in metadata.items():
                    if isinstance(value, (int, float)):
                        custom_metadata.append(
                            {"key": key, "numeric_value": value}
                        )
                    else:
                        custom_metadata.append(
                            {
                                "key": key,
                                "string_value": str(value),
                            }
                        )

            # 파일 업로드 및 스토어 추가 (1단계)
            upload_start = time.time()
            store_manager = self.client.file_search_stores
            operation = store_manager.upload_to_file_search_store(
                file_search_store_name=store.name,
                file=file_path,
                config={
                    "chunking_config": {
                        "white_space_config": {
                            "max_tokens_per_chunk": (
                                settings.FS_CHUNKING_MAX_TOKENS
                            ),
                            "max_overlap_tokens": (
                                settings.FS_CHUNKING_OVERLAP_TOKENS
                            ),
                        }
                    },
                    "custom_metadata": custom_metadata,
                },
            )
            upload_time = time.time() - upload_start

            # Polling 루프 (인덱싱 대기)
            max_wait = settings.FS_UPLOAD_TIMEOUT
            elapsed = 0
            poll_interval = settings.FS_POLL_INTERVAL

            logger.info(
                f"기준 문서 업로드 시작: {title}, "
                f"인덱싱 대기 중..."
            )

            while not operation.done and elapsed < max_wait:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                try:
                    operation = self.client.operations.get(operation)
                    logger.debug(
                        f"인덱싱 진행 중... (경과: {elapsed}초)"
                    )
                except Exception as e:
                    logger.info(
                        f"Operation 빠른 완료 감지: {str(e)}"
                    )
                    break

            if not operation.done:
                raise TimeoutError(
                    f"기준 문서 업로드 타임아웃 "
                    f"({max_wait}초 초과): {title}"
                )

            # Store ID 및 Document ID 추출
            vector_store_id = operation.response.parent
            document_id = operation.response.document_name

            # 총 소요 시간 계산
            total_time = time.time() - total_start

            logger.info(
                f"기준 문서 업로드 및 임베딩 완료: {title}\n"
                f"  - Vector Store ID: {vector_store_id}\n"
                f"  - Document ID: {document_id}\n"
                f"  - 소요 시간: {elapsed}초"
            )

            # 성능 메트릭 로깅
            logger.info(
                f"성능 메트릭 [{title}]: "
                f"스토어생성={store_time:.2f}s, "
                f"업로드시작={upload_time:.2f}s, "
                f"인덱싱대기={elapsed}s, "
                f"총소요={total_time:.2f}s"
            )

            return vector_store_id, document_id

        except Exception as e:
            logger.error(
                f"기준 문서 업로드 실패: {title} - {str(e)}"
            )

            # 실패 시 스토어 정리
            if store:
                logger.warning(
                    f"업로드 실패, 스토어 정리 시도: {store.name}"
                )
                try:
                    await self.delete_store(
                        store.name,
                        ignore_errors=True
                    )
                except Exception as cleanup_error:
                    logger.error(
                        f"스토어 정리 중 추가 오류: "
                        f"{cleanup_error}"
                    )

            # 원래 예외 재발생
            raise

    async def delete_file(
        self,
        file_id: str,
        ignore_errors: bool = False
    ) -> bool:
        """
        독립적인 파일 객체 삭제

        Args:
            file_id: 삭제할 Google File ID
            ignore_errors: True면 예외를 삼키고 False 반환,
                          False면 예외를 재발생 (기본값)

        Returns:
            성공 시 True,
            ignore_errors=True이고 실패 시 False

        Raises:
            Exception: ignore_errors=False이고 삭제 실패 시
        """
        try:
            if not file_id:
                logger.warning("삭제할 File ID가 없습니다.")
                return False

            # 파일 삭제 API 호출
            self.client.files.delete(name=file_id)

            logger.info(f"파일 삭제 완료: file_id={file_id}")
            return True

        except Exception as e:
            # 404는 이미 삭제된 경우로 간주
            error_msg = str(e).lower()
            if "404" in error_msg or "not found" in error_msg:
                logger.warning(
                    f"파일이 이미 삭제되었거나 존재하지 않습니다: "
                    f"{file_id}"
                )
                # 404는 성공으로 간주
                return True

            logger.error(f"파일 삭제 실패 (file_id: {file_id}): {e}")

            if ignore_errors:
                return False
            else:
                raise

    async def delete_store(
        self,
        vector_store_id: str,
        ignore_errors: bool = False
    ) -> bool:
        """
        Vector Store 삭제

        Args:
            vector_store_id: 삭제할 Google File Search Store ID
            ignore_errors: True면 예외를 삼키고 False 반환,
                          False면 예외를 재발생 (기본값)

        Returns:
            성공 시 True,
            ignore_errors=True이고 실패 시 False

        Raises:
            Exception: ignore_errors=False이고 삭제 실패 시
        """
        try:
            if not vector_store_id:
                logger.warning("삭제할 Vector Store ID가 없습니다.")
                return False

            self.client.file_search_stores.delete(name=vector_store_id)

            logger.info(
                f"Vector Store 삭제 완료: {vector_store_id}"
            )
            return True

        except Exception as e:
            error_msg = str(e).lower()

            # 404: 이미 삭제된 경우
            # 403: 권한 없음 또는 이미 삭제됨
            if ("404" in error_msg or "not found" in error_msg or
                "403" in error_msg or "permission_denied" in error_msg):
                logger.warning(
                    f"Store가 이미 삭제되었거나 접근 권한이 없습니다: "
                    f"{vector_store_id}"
                )
                # 404/403는 성공으로 간주 (이미 삭제되었거나 접근 불가)
                return True

            # FAILED_PRECONDITION: 스토어 내부에 문서가 남아있음
            if "failed_precondition" in error_msg or "400" in error_msg:
                logger.error(
                    f"Vector Store 삭제 실패 - "
                    f"스토어 내부에 문서가 남아있습니다: "
                    f"{vector_store_id}. "
                    f"문서를 먼저 삭제해야 합니다."
                )
                if not ignore_errors:
                    raise ValueError(
                        f"스토어 내부에 문서가 남아있어 삭제할 수 "
                        f"없습니다. 문서를 먼저 삭제하세요."
                    ) from e
                return False

            # 기타 에러
            logger.error(
                f"Vector Store 삭제 실패 "
                f"(ID: {vector_store_id}): {e}"
            )

            if ignore_errors:
                # 로컬 DB 삭제는 계속 진행
                return False
            else:
                # 트랜잭션 롤백 유도
                raise
