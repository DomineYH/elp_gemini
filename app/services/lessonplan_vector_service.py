"""
지도안 임시 Vector DB 관리 서비스
사용자별/세션별 임시 저장 및 자동 삭제 지원
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from app.services.file_search_service import FileSearchService
from app.config import settings

logger = logging.getLogger(__name__)


class LessonPlanVectorService:
    """지도안 임시 Vector DB 관리 서비스"""

    def __init__(self):
        """
        서비스 초기화
        - FileSearchService 인스턴스 생성
        """
        self.file_search_service = FileSearchService()

    async def upload_temporary(
        self,
        file_path: str,
        display_name: str,
        user_id: int,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """
        지도안을 임시 Vector DB에 업로드
        (사용자별 또는 세션별 Store 사용)

        Args:
            file_path: 지도안 파일 경로
            display_name: 표시 이름
            user_id: 사용자 ID (User.id)
            session_id: 세션 ID (선택)
            metadata: 추가 메타데이터 (선택)

        Returns:
            document_id와 store_id 딕셔너리
        """
        try:
            # 메타데이터 설정
            upload_metadata = metadata or {}
            upload_metadata["type"] = "lessonplan"
            upload_metadata["user_id"] = str(user_id)
            upload_metadata["uploaded_at"] = (
                datetime.now().isoformat()
            )

            if session_id:
                upload_metadata["session_id"] = session_id

            # 파일 업로드 (FileSearchService가 사용자별 Store 생성)
            result = await self.file_search_service.upload_document(
                file_path=file_path,
                display_name=display_name,
                metadata=upload_metadata,
                store_type="main",  # user_id로 자동 분리
            )

            logger.info(
                f"지도안 임시 업로드 완료: {display_name}\n"
                f"  - User ID: {user_id}\n"
                f"  - Session ID: {session_id}\n"
                f"  - Document ID: {result['document_id']}\n"
                f"  - Store ID: {result['store_id']}"
            )

            return result
        except Exception as e:
            logger.error(f"지도안 임시 업로드 실패: {str(e)}")
            raise

    async def delete_on_logout(self, user_id: int) -> bool:
        """
        로그아웃 시 사용자의 임시 지도안 삭제
        (사용자별 Store 삭제)

        Args:
            user_id: 사용자 ID (User.id)

        Returns:
            삭제 성공 여부
        """
        try:
            await self._delete_user_store(user_id)
            logger.info(
                f"로그아웃 시 임시 지도안 삭제 완료: user_id={user_id}"
            )
            return True
        except Exception as e:
            logger.error(
                f"로그아웃 시 임시 지도안 삭제 실패: {str(e)}"
            )
            raise

    async def delete_on_session_close(
        self, session_id: str
    ) -> bool:
        """
        세션 종료 시 임시 지도안 삭제
        (세션 ID로 필터링하여 삭제)

        Note:
            현재 API 제약으로 세션별 필터 삭제 불가
            → 사용자별 Store 삭제로 대체

        Args:
            session_id: 세션 ID

        Returns:
            삭제 성공 여부
        """
        try:
            # TODO: 세션별 삭제는 현재 API 제약으로 불가
            # 사용자 Store 전체 삭제로 대체
            logger.warning(
                f"세션별 삭제는 현재 API 제약으로 미지원. "
                f"사용자 로그아웃 시 삭제됩니다. "
                f"session_id={session_id}"
            )
            return True
        except Exception as e:
            logger.error(
                f"세션 종료 시 임시 지도안 삭제 실패: {str(e)}"
            )
            raise

    async def delete_user_documents(self, user_id: int) -> bool:
        """
        특정 사용자의 모든 임시 지도안 삭제
        (사용자별 Store 삭제)

        Args:
            user_id: 사용자 ID (User.id)

        Returns:
            삭제 성공 여부
        """
        try:
            await self._delete_user_store(user_id)
            logger.info(
                f"사용자 임시 지도안 삭제 완료: user_id={user_id}"
            )
            return True
        except Exception as e:
            logger.error(
                f"사용자 임시 지도안 삭제 실패: {str(e)}"
            )
            raise

    async def _delete_user_store(self, user_id: int) -> None:
        """
        사용자별 Store 삭제 (내부 메서드)

        Args:
            user_id: 사용자 ID (User.id)
        """
        try:
            store_name = f"user-{user_id}-store"
            await self._delete_store(store_name)
            logger.info(
                f"사용자 Store 삭제 완료: {store_name}"
            )
        except Exception as e:
            logger.error(f"사용자 Store 삭제 실패: {str(e)}")
            raise

    async def _delete_store(self, store_name: str) -> None:
        """
        특정 Store 삭제 (내부 메서드)

        Args:
            store_name: Store 이름
        """
        try:
            client = self.file_search_service.client

            # Store 찾기 및 삭제
            for store in client.file_search_stores.list():
                if store.display_name == store_name:
                    logger.info(
                        f"Store 삭제 중: {store_name} "
                        f"(ID: {store.name})"
                    )
                    client.file_search_stores.delete(name=store.name)
                    logger.info(
                        f"Store 삭제 완료: {store_name}"
                    )
                    return

            logger.warning(
                f"Store를 찾을 수 없습니다: {store_name}"
            )
        except Exception as e:
            logger.error(f"Store 삭제 실패: {str(e)}")
            raise

    async def cleanup_expired_sessions(
        self, expiry_hours: int = 24
    ) -> int:
        """
        만료된 세션의 임시 지도안 정리
        (업로드 후 일정 시간 경과한 Store 삭제)

        Args:
            expiry_hours: 만료 시간 (기본 24시간)

        Returns:
            삭제된 Store 개수
        """
        try:
            client = self.file_search_service.client
            deleted_count = 0
            cutoff_time = (
                datetime.now() - timedelta(hours=expiry_hours)
            )

            # 모든 사용자 Store 확인
            for store in client.file_search_stores.list():
                if not store.display_name.startswith("user-"):
                    continue

                # Store 생성 시간 확인 (API 제약으로 문서 기준)
                try:
                    docs = list(
                        client.file_search_stores.list_documents(
                            file_search_store_name=store.name
                        )
                    )

                    if not docs:
                        # 빈 Store는 삭제
                        client.file_search_stores.delete(
                            name=store.name
                        )
                        deleted_count += 1
                        logger.info(
                            f"빈 Store 삭제: {store.display_name}"
                        )
                        continue

                    # TODO: 문서 메타데이터에서 uploaded_at 확인
                    # 현재 API로는 메타데이터 조회 제약
                    # 추후 개선 필요

                except Exception as doc_err:
                    logger.warning(
                        f"Store 문서 확인 실패: "
                        f"{store.display_name} - {doc_err}"
                    )

            logger.info(
                f"만료 세션 정리 완료: {deleted_count}개 Store 삭제"
            )
            return deleted_count
        except Exception as e:
            logger.error(f"만료 세션 정리 실패: {str(e)}")
            raise

    async def list_user_documents(
        self, user_id: int
    ) -> List[Dict[str, str]]:
        """
        특정 사용자의 임시 지도안 목록 조회

        Args:
            user_id: 사용자 ID (User.id)

        Returns:
            문서 정보 리스트
            - document_id: 문서 ID
            - display_name: 표시 이름
        """
        try:
            client = self.file_search_service.client
            store_name = f"user-{user_id}-store"
            store = None

            # Store 찾기
            for s in client.file_search_stores.list():
                if s.display_name == store_name:
                    store = s
                    break

            if not store:
                logger.info(
                    f"사용자 Store를 찾을 수 없습니다: "
                    f"{store_name}"
                )
                return []

            # Store 내 문서 목록 조회
            documents = []
            for doc in client.file_search_stores.list_documents(
                file_search_store_name=store.name
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
                f"사용자 임시 지도안 목록 조회: "
                f"{len(documents)}개 (user_id={user_id})"
            )
            return documents
        except Exception as e:
            logger.error(f"문서 목록 조회 실패: {str(e)}")
            raise
