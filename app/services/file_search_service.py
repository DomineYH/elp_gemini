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
            cls._client = genai.Client(
                api_key=settings.GOOGLE_API_KEY,
                http_options={'api_version': 'v1beta'}
            )
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

    def get_dual_store_ids(self, user_key: str) -> list[str]:
        """
        rubricstore와 사용자 스토어 ID 조회/생성

        Args:
            user_key: 사용자 식별키 (username)

        Returns:
            [user_store_id, rubricstore_id]  # 사용자 문서 우선 검색

        Raises:
            ValueError: rubricstore를 찾을 수 없는 경우
        """
        import time

        store_ids = []

        # 1. 캐시 확인 (60초 TTL)
        cache_key = f"dual_store_{user_key}"
        if not hasattr(self, '_store_cache'):
            self._store_cache = {}

        cached = self._store_cache.get(cache_key)
        if cached and time.time() - cached['time'] < 60:
            logger.debug(f"캐시에서 Store ID 조회: {user_key}")
            return cached['ids']

        # 2. rubricstore 조회
        rubric_store_id = None
        for store in self.client.file_search_stores.list():
            # 하이픈, 언더스코어 제거 후 비교
            normalized_name = (
                store.display_name.lower()
                .replace("-", "")
                .replace("_", "")
            )
            if "rubricstore" in normalized_name:
                rubric_store_id = store.name
                logger.info(
                    f"✅ rubricstore 발견: "
                    f"{store.display_name} -> {store.name}"
                )
                break

        if not rubric_store_id:
            logger.error("❌ rubricstore를 찾을 수 없습니다")
            raise ValueError(
                "평가기준 스토어(rubricstore)를 찾을 수 없습니다. "
                "관리자에게 문의하세요."
            )

        # 3. 사용자 스토어 조회 또는 생성
        user_store_name = f"user-{user_key}-store"
        user_store_id = None

        for store in self.client.file_search_stores.list():
            if user_store_name in store.display_name.lower():
                user_store_id = store.name
                logger.info(
                    f"✅ 사용자 스토어 발견: {store.name} "
                    f"(user_key={user_key})"
                )
                break

        if not user_store_id:
            # 생성
            logger.info(
                f"📦 사용자 스토어 생성 시작: {user_store_name}"
            )
            created_store = self._get_or_create_store(
                user_store_name
            )
            user_store_id = created_store.name
            logger.info(
                f"✅ 사용자 스토어 생성 완료: {user_store_id}"
            )

        # 사용자 문서 우선 검색을 위해 user store를 먼저 추가
        store_ids.append(user_store_id)
        store_ids.append(rubric_store_id)

        # 4. 캐싱
        self._store_cache[cache_key] = {
            'ids': store_ids,
            'time': time.time()
        }

        logger.info(
            f"🎯 Store ID 조회 완료 (우선순위 순): "
            f"user-{user_key}-store (1순위) + rubricstore (2순위)"
        )
        return store_ids

    def get_user_store_id(self, user_key: str) -> str:
        """
        사용자 스토어 ID만 조회/생성

        Args:
            user_key: 사용자 식별키 (username)

        Returns:
            user_store_id

        Raises:
            ValueError: 사용자 스토어를 찾거나 생성할 수 없는 경우
        """
        import time

        # 1. 캐시 확인 (60초 TTL)
        cache_key = f"user_store_{user_key}"
        if not hasattr(self, '_store_cache'):
            self._store_cache = {}

        cached = self._store_cache.get(cache_key)
        if cached and time.time() - cached['time'] < 60:
            logger.debug(f"캐시에서 사용자 Store ID 조회: {user_key}")
            return cached['id']

        # 2. 사용자 스토어 조회 또는 생성
        user_store_name = f"user-{user_key}-store"
        user_store_id = None

        for store in self.client.file_search_stores.list():
            if user_store_name in store.display_name.lower():
                user_store_id = store.name
                logger.info(
                    f"✅ 사용자 스토어 발견: {store.name} "
                    f"(user_key={user_key})"
                )
                break

        if not user_store_id:
            # 생성
            logger.info(
                f"📦 사용자 스토어 생성 시작: {user_store_name}"
            )
            created_store = self._get_or_create_store(
                user_store_name
            )
            user_store_id = created_store.name
            logger.info(
                f"✅ 사용자 스토어 생성 완료: {user_store_id}"
            )

        # 3. 캐싱
        self._store_cache[cache_key] = {
            'id': user_store_id,
            'time': time.time()
        }

        logger.info(
            f"🎯 사용자 Store ID 조회 완료: user-{user_key}-store"
        )
        return user_store_id

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
            if store_type == "rubric":
                store_name = self.rubric_store_name
            else:
                # 메인 스토어 대신 사용자별 스토어 사용
                user_key = metadata.get("user_id")  # user_id 키에 username 저장됨
                if user_key:
                    store_name = f"user-{user_key}-store"
                else:
                    store_name = self.main_store_name
            
            store = self._get_or_create_store(store_name)

            # 문서 타입 메타데이터 자동 추가
            if store_type == "rubric":
                metadata["document_type"] = "rubric"
            else:
                metadata["document_type"] = "user_document"

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

    async def delete_store_by_display_name(self, display_name: str) -> None:
        """
        Display Name으로 File Search Store 삭제

        Note:
            force=True 옵션을 사용하면 스토어 내의 모든 문서가 자동으로 삭제됩니다.
            documents.list()와 documents.delete()는 Python SDK에 존재하지 않는 메서드입니다.

        Args:
            display_name: 스토어 표시 이름
        """
        try:
            target_store = None
            # 스토어 목록에서 이름으로 검색
            for store in self.client.file_search_stores.list():
                if store.display_name == display_name:
                    target_store = store
                    break

            if target_store:
                # Store 삭제 (force=True로 내부 문서와 함께 삭제)
                self.client.file_search_stores.delete(
                    name=target_store.name,
                    config={'force': True}  # 내부 문서와 함께 강제 삭제
                )
                logger.info(f"스토어 삭제 완료: {display_name} ({target_store.name})")
            else:
                logger.info(f"삭제할 스토어를 찾지 못함 (무시): {display_name}")
        except Exception as e:
            logger.warning(f"스토어 삭제 중 오류 발생: {str(e)}")

    async def search_in_store(
        self,
        query: str,
        store_name: str,
        model: str = "gemini-2.5-flash",
        metadata_filter: Optional[str] = None,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """
        File Search Store에서 문서 검색 및 답변 생성

        Args:
            query: 검색 쿼리
            store_name: 스토어 이름 (예: fileSearchStores/xxxxx)
            model: 사용할 모델 (기본: gemini-2.0-flash-exp)
            metadata_filter: 메타데이터 필터 (예: 'type="criteria"')
            temperature: 생성 온도

        Returns:
            response_text: 생성된 답변
            citations: 인용 정보
            sources_count: 참조 소스 개수
        """
        try:
            # File Search Tool 구성
            file_search_config = {
                "file_search_store_names": [store_name]
            }
            if metadata_filter:
                file_search_config["metadata_filter"] = metadata_filter

            # Generate Content 요청
            response = self.client.models.generate_content(
                model=model,
                contents=query,
                config=types.GenerateContentConfig(
                    tools=[
                        types.Tool(
                            file_search=types.FileSearch(
                                **file_search_config
                            )
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

    def _extract_citations(
        self, response
    ) -> list[Dict[str, Any]]:
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
                                if hasattr(
                                    chunk.retrieved_context, "uri"
                                )
                                else None
                            )
                            citation_info["title"] = (
                                chunk.retrieved_context.title
                                if hasattr(
                                    chunk.retrieved_context, "title"
                                )
                                else None
                            )

                        citations.append(citation_info)

                logger.debug(f"추출된 citations: {len(citations)}개")

        except Exception as e:
            logger.warning(f"Citation 추출 실패: {str(e)}")

        return citations
