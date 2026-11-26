"""
Google File Search 서비스
문서 업로드, 인덱싱, RAG 쿼리
"""

import asyncio
import base64
import logging
import os
import re
import tempfile
import unicodedata
from datetime import datetime
from typing import Any, Dict, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import settings
from app.services.operation_polling import poll_operation
from app.utils.gemini_retry import retry_on_resource_exhausted

logger = logging.getLogger(__name__)

_MANIFEST_PAYLOAD_METADATA_KEY = "manifest_payload_base64"
# Google File Search caps each string_list_value entry at 256 chars (issue #60).
# Keep in sync with alias_map_codec._CHUNK_SIZE.
_MANIFEST_PAYLOAD_CHUNK_SIZE = 240
# 스토어 목록 조회(GET) 요청 하나의 제한. 평소 0.6초인데 기본 120초는 길다 (#464)
_STORE_LIST_TIMEOUT_MS = 10_000


def _sanitize_display_name(name: str) -> str:
    """
    display_name을 ASCII 안전한 문자열로 변환

    HTTP 헤더로 전달되는 display_name에 한글이 포함되면
    UnicodeEncodeError가 발생하므로 ASCII로 변환합니다.

    Args:
        name: 원본 파일명

    Returns:
        ASCII 안전한 문자열
    """
    # 1. 유니코드 정규화 후 ASCII 문자만 유지
    normalized = unicodedata.normalize("NFD", name)
    ascii_safe = "".join(
        c
        for c in normalized
        if unicodedata.category(c) != "Mn" and ord(c) < 128
    )

    # 2. 빈 문자열이면 타임스탬프로 대체
    if not ascii_safe.strip():
        ascii_safe = f"doc_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # 3. 특수문자를 underscore로 치환
    sanitized = re.sub(r"[^\w\.\-]", "_", ascii_safe)

    # 4. 연속 underscore 정리
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")

    logger.debug(f"display_name 변환: {name} -> {sanitized}")
    return sanitized


def _metadata_value(entry, field_name: str):
    if isinstance(entry, dict):
        return entry.get(field_name)
    return getattr(entry, field_name, None)


def _manifest_payload_metadata(content: bytes) -> list[dict]:
    encoded = base64.b64encode(content).decode("ascii")
    chunks = [
        encoded[i : i + _MANIFEST_PAYLOAD_CHUNK_SIZE]
        for i in range(0, len(encoded), _MANIFEST_PAYLOAD_CHUNK_SIZE)
    ] or [""]
    return [
        {
            "key": _MANIFEST_PAYLOAD_METADATA_KEY,
            "string_list_value": {"values": chunks},
        }
    ]


def _payload_from_metadata(custom_metadata) -> bytes | None:
    for entry in custom_metadata or []:
        if _metadata_value(entry, "key") != _MANIFEST_PAYLOAD_METADATA_KEY:
            continue

        string_list = _metadata_value(entry, "string_list_value")
        if string_list is None:
            string_list = _metadata_value(entry, "stringListValue")

        if isinstance(string_list, dict):
            values = string_list.get("values") or []
        else:
            values = getattr(string_list, "values", None) or []

        if not values:
            single_value = _metadata_value(entry, "string_value")
            if single_value is None:
                single_value = _metadata_value(entry, "stringValue")
            values = [single_value] if single_value else []

        if not values:
            return None

        encoded = "".join(values)
        return base64.b64decode(encoded.encode("ascii"))

    return None


@retry_on_resource_exhausted(retry_timeouts=True)
def list_stores(client) -> list:
    """스토어 목록 전체(GET). 요청마다 10초 제한, 일시 오류와 시간 초과는 3번까지 부른다 (#464).

    소진되면 429는 GeminiQuotaExhausted, 5xx는 GeminiServerOverloaded,
    전송 오류는 httpx 예외 그대로 올린다.
    """
    # 다음 쪽 요청도 재시도 안에 들도록 여기서 끝까지 읽는다
    return list(
        client.file_search_stores.list(
            config={"http_options": {"timeout": _STORE_LIST_TIMEOUT_MS}}
        )
    )


@retry_on_resource_exhausted(retry_timeouts=True)
def _get_store(client, store_id: str):
    """스토어 하나 조회(GET). 제한과 재시도는 list_stores 와 같다 (#464)."""
    return client.file_search_stores.get(
        name=store_id,
        config={"http_options": {"timeout": _STORE_LIST_TIMEOUT_MS}},
    )


class RubricStoreNotFound(ValueError):
    """설정 이름(FS_RUBRIC_STORE_NAME)의 평가기준 스토어가 클라우드에 없다."""


class FileSearchService:
    """File Search 서비스 클래스"""

    _client = None

    @classmethod
    def get_client(cls):
        """싱글톤 Client 인스턴스 반환"""
        if cls._client is None:
            cls._client = genai.Client(
                api_key=settings.GOOGLE_API_KEY,
                http_options=types.HttpOptions(
                    api_version="v1beta",
                    timeout=settings.GEMINI_HTTP_TIMEOUT_MS,
                ),
            )
        return cls._client

    def __init__(self):
        """
        FileSearchService 초기화
        - Google API 키 검증
        - 클라이언트 초기화
        """
        if not settings.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다")

        self._store_cache = {}

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
            main_store = self._get_or_create_store(self.main_store_name)
            rubric_store = self._get_or_create_store(self.rubric_store_name)

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
        # store_name을 ASCII 안전하게 변환 (HTTP 헤더 호환)
        safe_store_name = _sanitize_display_name(store_name)
        logger.debug(f"스토어 이름 변환: {store_name} -> {safe_store_name}")

        try:
            # 기존 스토어 찾기 (sanitized name으로 검색)
            for store in self.client.file_search_stores.list():
                if store.display_name == safe_store_name:
                    logger.info(
                        f"기존 스토어 발견: {safe_store_name} (ID: {store.name})"
                    )
                    return store

            # 없으면 새로 생성
            store = self.client.file_search_stores.create(
                config={"display_name": safe_store_name}
            )
            logger.info(f"새 스토어 생성: {safe_store_name} (ID: {store.name})")
            return store
        except Exception as e:
            logger.error(f"스토어 처리 실패: {str(e)}")
            raise

    def get_rubric_store_id(self) -> str:
        """
        평가기준 스토어 ID 조회

        Returns:
            rubric_store_id

        Raises:
            RubricStoreNotFound: 설정 이름의 스토어가 없는 경우
        """
        import time

        # 1. 캐시 확인 (60초 TTL)
        cache_key = "rubric_store"
        cached = self._store_cache.get(cache_key)
        if cached and time.time() - cached["time"] < 60:
            logger.debug("캐시에서 평가기준 Store ID 조회")
            return cached["id"]

        # 2. 평가기준 스토어 조회
        # 설정 이름과 정확히 같은 스토어만 쓴다. 비슷한 이름은 다른 배포의 것일 수 있다 (#470)
        rubric_store_name = settings.FS_RUBRIC_STORE_NAME
        rubric_store_id = next(
            (
                s.name
                for s in list_stores(self.client)
                if s.display_name == rubric_store_name
            ),
            None,
        )

        if not rubric_store_id:
            logger.error(f"❌ 평가기준 스토어 없음: {rubric_store_name}")
            raise RubricStoreNotFound(
                "평가기준 스토어(rubricstore)를 찾을 수 없습니다. "
                "관리자에게 문의하세요."
            )

        # 3. 캐싱
        self._store_cache[cache_key] = {
            "id": rubric_store_id,
            "time": time.time(),
        }
        return rubric_store_id

    def store_exists(self, store_id: str) -> bool:
        """업로드 행이 가리키는 스토어가 클라우드에 남아 있는지 (GET 1회).

        없는 스토어는 404 또는 403(없거나 접근할 수 없음)으로 온다.
        그 밖의 오류는 그대로 올린다.
        """
        try:
            _get_store(self.client, store_id)
        except genai_errors.ClientError as e:
            code = getattr(e, "code", None)
            if code in (403, 404):
                logger.info("스토어가 클라우드에 없음: %s (%s)", store_id, code)
                return False
            raise
        return True

    async def upload_document(
        self,
        file_path: str,
        display_name: str,
        metadata: Dict[str, Any] | list[dict],
        store_type: str = "main",
    ) -> Dict[str, str]:
        """
        문서를 File Search Store에 업로드 (최신 API)

        Args:
            file_path: 파일 경로
            display_name: 표시 이름
            metadata: 메타데이터 dict 또는 SDK custom_metadata list
            store_type: 스토어 타입 (main/rubric)

        Returns:
            document_id와 store_id 포함 딕셔너리
        """
        # 이 호출이 만든 사용자 스토어. 실패하면 지운다 (#470)
        new_store_id = None
        try:
            # 스토어 선택
            per_upload_store = False
            if store_type == "rubric":
                store_name = self.rubric_store_name
            elif isinstance(metadata, dict):
                # 메인 스토어 대신 사용자별 스토어 사용
                user_key = metadata.get(
                    "user_id"
                )  # user_id 키에 User.id 저장됨
                if user_key:
                    store_name = f"user-{user_key}-store"
                    per_upload_store = True
                else:
                    store_name = self.main_store_name
            else:
                store_name = self.main_store_name

            if per_upload_store:
                # 사용자 스토어는 이름으로 찾지 않고 업로드마다 새로 만든다.
                # 같은 이름의 스토어는 다른 배포의 것일 수 있다 (#470)
                store = await asyncio.to_thread(
                    self.client.file_search_stores.create,
                    config={"display_name": _sanitize_display_name(store_name)},
                )
                new_store_id = store.name
            else:
                store = await asyncio.to_thread(
                    self._get_or_create_store, store_name
                )

            document_type = (
                "rubric" if store_type == "rubric" else "user_document"
            )
            if isinstance(metadata, list):
                custom_metadata = [dict(entry) for entry in metadata]
                has_document_type = any(
                    _metadata_value(entry, "key") == "document_type"
                    for entry in custom_metadata
                )
                if not has_document_type:
                    custom_metadata.append(
                        {
                            "key": "document_type",
                            "string_value": document_type,
                        }
                    )
            else:
                metadata = dict(metadata)
                metadata["document_type"] = document_type

                # Custom metadata 구조 변환 (string_value도 ASCII 안전하게)
                custom_metadata = []
                for key, value in metadata.items():
                    if isinstance(value, (int, float)):
                        custom_metadata.append(
                            {"key": key, "numeric_value": value}
                        )
                    else:
                        # string_value도 ASCII 안전하게 변환 (HTTP 헤더 호환)
                        safe_value = _sanitize_display_name(str(value))
                        custom_metadata.append(
                            {"key": key, "string_value": safe_value}
                        )

            # display_name을 ASCII 안전하게 변환 (HTTP 헤더 호환)
            safe_display_name = _sanitize_display_name(display_name)

            # 직접 업로드 및 청킹 설정
            operation = await asyncio.to_thread(
                self.client.file_search_stores.upload_to_file_search_store,
                file_search_store_name=store.name,
                file=file_path,
                config={
                    "display_name": safe_display_name,  # ASCII 안전한 이름 사용
                    "chunking_config": {
                        "white_space_config": {
                            "max_tokens_per_chunk": settings.FS_CHUNKING_MAX_TOKENS,
                            "max_overlap_tokens": settings.FS_CHUNKING_OVERLAP_TOKENS,
                        }
                    },
                    "custom_metadata": custom_metadata,
                },
            )

            logger.info(f"파일 업로드 시작: {display_name}, 인덱싱 대기 중...")
            operation = await poll_operation(
                self.client,
                operation,
                deadline_s=settings.FS_UPLOAD_TIMEOUT,
                interval_s=settings.FS_POLL_INTERVAL,
                label=f"파일 업로드 {display_name}",
            )

            # API 응답 구조: document_name, parent 속성 사용
            document_id = operation.response.document_name
            store_id = operation.response.parent
            if not store_id:
                raise RuntimeError(
                    f"업로드 응답에 parent가 없다: {display_name}"
                )

            logger.info(
                f"문서 업로드 및 인덱싱 완료: {display_name}\n"
                f"  - Document ID: {document_id}\n"
                f"  - Store ID: {store_id}"
            )

            return {
                "document_id": document_id,
                "store_id": store_id,
            }
        except Exception as e:
            logger.error(f"문서 업로드 실패: {str(e)}")
            if new_store_id:
                await self.discard_store(new_store_id)
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
            await asyncio.to_thread(self.client.files.delete, name=file_id)
            logger.info(f"문서 삭제 완료: {file_id}")
        except Exception as e:
            logger.warning(
                f"문서 삭제 실패 (이미 삭제되었을 수 있음): {str(e)}"
            )

    async def delete_store(self, store_id: str) -> None:
        """
        자원 이름(fileSearchStores/...)으로 File Search Store 삭제

        Note:
            force=True 옵션을 사용하면 스토어 내의 모든 문서가 자동으로 삭제됩니다.
            표시 이름으로는 지우지 않는다. 같은 이름의 스토어는 다른 배포의
            것일 수 있다 (#470)

        Raises:
            조회·삭제 실패를 그대로 올린다. 스토어가 없으면 조용히 끝난다 (#466)
        """
        await asyncio.to_thread(self._delete_store_sync, store_id)

    def _delete_store_sync(self, store_id: str) -> None:
        # 이미 지워진 스토어는 목록에 없다. 없는 것을 지우다 실패로 끝나지 않게 한다
        if any(store.name == store_id for store in list_stores(self.client)):
            self.client.file_search_stores.delete(
                name=store_id,
                config={"force": True},  # 내부 문서와 함께 강제 삭제
            )
            logger.info(f"스토어 삭제 완료: {store_id}")
        else:
            logger.info(f"삭제할 스토어를 찾지 못함 (무시): {store_id}")

    async def discard_store(self, store_id: str) -> None:
        """행에 적히지 못한 새 스토어를 지운다. 실패는 경고만 남긴다 (#470)"""
        try:
            await asyncio.to_thread(
                self.client.file_search_stores.delete,
                name=store_id,
                config={"force": True},
            )
        except Exception as e:
            # 원문에는 응답 헤더 줄이 섞일 수 있어 종류만 남긴다 (#368)
            logger.warning(
                "새 스토어 정리 실패 (남은 스토어): %s, %s",
                store_id,
                type(e).__name__,
            )

    async def search_in_store(
        self,
        query: str,
        store_name: str,
        model: str = None,
        metadata_filter: Optional[str] = None,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """
        File Search Store에서 문서 검색 및 답변 생성

        Args:
            query: 검색 쿼리
            store_name: 스토어 이름 (예: fileSearchStores/xxxxx)
            model: 사용할 모델 (None이면 settings.GEMINI_QNA_MODEL 사용)
            metadata_filter: 메타데이터 필터 (예: 'type="criteria"')
            temperature: 생성 온도

        Returns:
            response_text: 생성된 답변
            citations: 인용 정보
            sources_count: 참조 소스 개수
        """
        try:
            if model is None:
                model = settings.GEMINI_QNA_MODEL

            file_search_config = {"file_search_store_names": [store_name]}
            if metadata_filter:
                file_search_config["metadata_filter"] = metadata_filter

            # Generate Content 요청
            response = await asyncio.to_thread(
                retry_on_resource_exhausted()(
                    self.client.models.generate_content
                ),
                model=model,
                contents=query,
                config=types.GenerateContentConfig(
                    tools=[
                        types.Tool(
                            file_search=types.FileSearch(**file_search_config)
                        )
                    ],
                    temperature=temperature,
                ),
            )

            # 응답 텍스트 추출
            response_text = response.text if response.text else ""

            # Citation 정보 추출
            citations = self._extract_citations(response)

            logger.info(
                f"검색 완료: query={query[:50]}..., "
                f"sources={len(citations)}"
            )

            return {
                "response_text": response_text,
                "citations": citations,
                "sources_count": len(citations),
            }
        except Exception as e:
            logger.error(f"검색 실패: {str(e)}")
            raise

    async def get_or_create_store(self, store_name: str) -> tuple[str, bool]:
        """스토어를 찾거나 생성하여 (store_id, created) 반환."""
        safe_name = _sanitize_display_name(store_name)
        stores = await asyncio.to_thread(
            lambda: list(self.client.file_search_stores.list())
        )
        for store in stores:
            if store.display_name == safe_name:
                return store.name, False
        store = await asyncio.to_thread(
            self.client.file_search_stores.create,
            config={"display_name": safe_name},
        )
        return store.name, True

    async def list_documents(self, store_id: str) -> list:
        """스토어 내 문서 목록 반환."""
        return await asyncio.to_thread(
            lambda: list(
                self.client.file_search_stores.documents.list(parent=store_id)
            )
        )

    async def download_document_bytes(
        self, store_id: str, document_name: str
    ) -> bytes:
        """문서의 원본 바이트 다운로드."""
        doc = await asyncio.to_thread(
            self.client.file_search_stores.documents.get, name=document_name
        )
        if hasattr(doc, "content") and doc.content:
            return doc.content

        payload = _payload_from_metadata(getattr(doc, "custom_metadata", None))
        if payload is not None:
            return payload

        raise RuntimeError(
            "File Search document raw bytes are not downloadable; "
            "manifest payload metadata is missing"
        )

    async def replace_single_document(
        self,
        store_id: str,
        display_name: str,
        content: bytes,
        mime_type: str = "application/json",
    ) -> str:
        """스토어에서 동일 display_name의 문서를 삭제 후 새로 업로드."""
        safe_name = _sanitize_display_name(display_name)
        # 기존 문서 삭제
        docs = await asyncio.to_thread(
            lambda: list(
                self.client.file_search_stores.documents.list(parent=store_id)
            )
        )
        for doc in docs:
            if getattr(doc, "display_name", "") == safe_name:
                await asyncio.to_thread(
                    self.client.file_search_stores.documents.delete,
                    name=doc.name,
                )
                break
        # 새 문서 업로드 (임시 파일 경유)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".json"
            ) as tmp_file:
                tmp_file.write(content)
                tmp_path = tmp_file.name

            operation = await asyncio.to_thread(
                self.client.file_search_stores.upload_to_file_search_store,
                file_search_store_name=store_id,
                file=tmp_path,
                config={
                    "display_name": safe_name,
                    "mime_type": mime_type,
                    "chunking_config": {
                        "white_space_config": {
                            "max_tokens_per_chunk": 512,
                        }
                    },
                    "custom_metadata": _manifest_payload_metadata(content),
                },
            )
            operation = await poll_operation(
                self.client,
                operation,
                deadline_s=30,
                interval_s=1,
                label=f"manifest 업로드 {safe_name}",
            )
            return operation.response.document_name
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _extract_citations(self, response) -> list[Dict[str, Any]]:
        """
        응답에서 Citation 정보 추출

        Args:
            response: Gemini API 응답

        Returns:
            Citation 정보 리스트
        """
        citations = []

        try:
            if (
                response.candidates
                and response.candidates[0].grounding_metadata
            ):
                grounding = response.candidates[0].grounding_metadata

                # Grounding chunks 처리
                if hasattr(grounding, "grounding_chunks"):
                    for chunk in grounding.grounding_chunks:
                        citation_info = {
                            "source": None,
                            "title": None,
                            "uri": None,
                        }

                        # Web source 처리
                        if hasattr(chunk, "web") and chunk.web:
                            citation_info["source"] = "web"
                            citation_info["uri"] = (
                                chunk.web.uri
                                if hasattr(chunk.web, "uri")
                                else None
                            )
                            citation_info["title"] = (
                                chunk.web.title
                                if hasattr(chunk.web, "title")
                                else None
                            )

                        # Retrieved context (File Search) 처리
                        elif (
                            hasattr(chunk, "retrieved_context")
                            and chunk.retrieved_context
                        ):
                            citation_info["source"] = "file_search"
                            citation_info["uri"] = (
                                chunk.retrieved_context.uri
                                if hasattr(chunk.retrieved_context, "uri")
                                else None
                            )
                            citation_info["title"] = (
                                chunk.retrieved_context.title
                                if hasattr(chunk.retrieved_context, "title")
                                else None
                            )

                        citations.append(citation_info)

                logger.debug(f"추출된 citations: {len(citations)}개")

        except Exception as e:
            logger.warning(f"Citation 추출 실패: {str(e)}")

        return citations
