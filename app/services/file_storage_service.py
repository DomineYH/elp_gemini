"""
파일 저장 서비스
로컬 파일 시스템에 파일 저장/삭제
"""
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FileStorageService:
    """로컬 파일 저장소 관리 서비스"""

    def __init__(self, base_dir: str = "criteria"):
        """
        초기화

        Args:
            base_dir: 기본 저장 디렉토리
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)

    def save_file(
        self,
        file_content: bytes,
        criteria_id: int,
        filename: str
    ) -> str:
        """
        파일을 로컬에 저장

        Args:
            file_content: 파일 내용
            criteria_id: 평가기준 ID
            filename: 원본 파일명

        Returns:
            저장된 파일의 전체 경로
        """
        # 파일명 생성: {criteria_id}_{filename}
        safe_filename = f"{criteria_id}_{filename}"
        file_path = self.base_dir / safe_filename

        try:
            with open(file_path, "wb") as f:
                f.write(file_content)

            logger.info(
                f"파일 저장 완료: {file_path} "
                f"({len(file_content)} bytes)"
            )
            return str(file_path)

        except Exception as e:
            logger.error(
                f"파일 저장 실패: {file_path}, "
                f"오류: {str(e)}",
                exc_info=True
            )
            raise

    def delete_file(self, file_path: str) -> bool:
        """
        파일 삭제

        Args:
            file_path: 삭제할 파일 경로

        Returns:
            삭제 성공 여부
        """
        try:
            path = Path(file_path)

            if not path.exists():
                logger.warning(
                    f"파일이 존재하지 않음: {file_path}"
                )
                return False

            path.unlink()
            logger.info(f"파일 삭제 완료: {file_path}")
            return True

        except Exception as e:
            logger.error(
                f"파일 삭제 실패: {file_path}, "
                f"오류: {str(e)}",
                exc_info=True
            )
            return False

    def get_file_path(
        self, criteria_id: int, filename: str
    ) -> str:
        """
        파일 경로 생성

        Args:
            criteria_id: 평가기준 ID
            filename: 파일명

        Returns:
            파일 경로
        """
        safe_filename = f"{criteria_id}_{filename}"
        return str(self.base_dir / safe_filename)

    def file_exists(self, file_path: str) -> bool:
        """
        파일 존재 여부 확인

        Args:
            file_path: 파일 경로

        Returns:
            존재 여부
        """
        return Path(file_path).exists()
