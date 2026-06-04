"""
지도안 파일 로컬 저장 서비스
data/lessonplan/{user_id}/ 디렉토리에 사용자별 지도안 파일 관리
"""
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class LessonPlanStorageService:
    """지도안 파일 로컬 저장 서비스"""

    def __init__(self, base_dir: str = "data/lessonplan"):
        """
        서비스 초기화

        Args:
            base_dir: 지도안 저장 기본 디렉토리
        """
        self.base_dir = Path(base_dir)
        self._ensure_directory_exists()

    def _ensure_directory_exists(self) -> None:
        """저장 디렉토리 존재 확인 및 생성"""
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"지도안 디렉토리 확인: {self.base_dir}")
        except Exception as e:
            logger.error(f"디렉토리 생성 실패: {str(e)}")
            raise

    def save_lessonplan(
        self,
        user_id: int,
        original_filename: str,
        file_content: bytes,
    ) -> Dict[str, str]:
        """
        지도안 파일 저장

        Returns:
            {
              "file_path": str,
              "filename": str,
              "timestamp": str (ISO),
              "file_hash": str (SHA-256 hex, 64 chars),
            }
        """
        try:
            user_dir = self.base_dir / str(user_id)
            user_dir.mkdir(parents=True, exist_ok=True)

            file_path = user_dir / original_filename

            with open(file_path, "wb") as f:
                f.write(file_content)

            file_hash = hashlib.sha256(file_content).hexdigest()

            logger.info(
                f"지도안 저장 완료: user_id={user_id}, "
                f"{original_filename} (hash={file_hash[:8]}…)"
            )

            return {
                "file_path": str(file_path),
                "filename": original_filename,
                "timestamp": datetime.now().isoformat(),
                "file_hash": file_hash,
            }
        except Exception as e:
            logger.error(f"지도안 저장 실패: {str(e)}")
            raise

    def get_lessonplan_path(
        self, user_id: int, original_filename: str
    ) -> Optional[str]:
        """
        지도안 파일 경로 반환

        Args:
            user_id: 사용자 ID
            original_filename: 원본 파일명

        Returns:
            파일 경로 (존재하지 않으면 None)
        """
        file_path = self.base_dir / str(user_id) / original_filename

        if file_path.exists():
            logger.debug(f"지도안 경로 조회: {file_path}")
            return str(file_path)

        logger.warning(
            f"지도안 파일 없음: user_id={user_id}, {original_filename}"
        )
        return None

    def list_lessonplans(self, user_id: int) -> List[Dict[str, str]]:
        """
        사용자별 지도안 목록 조회

        Args:
            user_id: 사용자 ID

        Returns:
            지도안 파일 정보 리스트
            - filename: 파일명
            - original_filename: 원본 파일명
            - file_path: 파일 경로
            - size: 파일 크기 (bytes)
            - created_at: 생성 시간
        """
        try:
            user_dir = self.base_dir / str(user_id)
            if not user_dir.is_dir():
                return []

            files = [
                f for f in user_dir.iterdir() if f.is_file()
            ]

            lessonplans = []
            for file_path in files:
                # 파일 정보 수집
                stat = file_path.stat()
                lessonplans.append(
                    {
                        "filename": file_path.name,
                        "original_filename": file_path.name,
                        "file_path": str(file_path),
                        "size": stat.st_size,
                        "created_at": datetime.fromtimestamp(
                            stat.st_ctime
                        ).isoformat(),
                    }
                )

            logger.info(
                f"지도안 목록 조회: user_id={user_id}, "
                f"{len(lessonplans)}개"
            )
            return lessonplans
        except Exception as e:
            logger.error(f"지도안 목록 조회 실패: {str(e)}")
            raise

    def delete_lessonplan(
        self, user_id: int, original_filename: str
    ) -> bool:
        """
        지도안 파일 삭제

        Args:
            user_id: 사용자 ID
            original_filename: 원본 파일명

        Returns:
            삭제 성공 여부
        """
        try:
            file_path = self.base_dir / str(user_id) / original_filename

            if not file_path.exists():
                logger.warning(
                    f"삭제할 파일 없음: user_id={user_id}, "
                    f"{original_filename}"
                )
                return False

            file_path.unlink()
            logger.info(
                f"지도안 삭제 완료: user_id={user_id}, "
                f"{original_filename}"
            )
            return True
        except Exception as e:
            logger.error(f"지도안 삭제 실패: {str(e)}")
            raise

    def get_storage_stats(self) -> Dict[str, int]:
        """
        저장소 통계 정보

        Returns:
            통계 정보 딕셔너리
            - total_files: 전체 파일 개수
            - total_size: 전체 크기 (bytes)
        """
        try:
            files = [
                f
                for f in self.base_dir.rglob("*")
                if f.is_file()
            ]
            total_size = sum(f.stat().st_size for f in files)

            return {
                "total_files": len(files),
                "total_size": total_size,
            }
        except Exception as e:
            logger.error(f"통계 정보 조회 실패: {str(e)}")
            raise
