"""
분석 보고서 파일 저장 서비스
app/static/reports/ 디렉토리에 분석 보고서 파일 관리
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ReportStorageService:
    """분석 보고서 파일 저장 서비스"""

    def __init__(self, base_dir: str = "app/static/reports"):
        """
        서비스 초기화

        Args:
            base_dir: 보고서 저장 기본 디렉토리
        """
        self.base_dir = Path(base_dir)
        self._ensure_directory_exists()

    def _ensure_directory_exists(self) -> None:
        """저장 디렉토리 존재 확인 및 생성"""
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"보고서 디렉토리 확인: {self.base_dir}")
        except Exception as e:
            logger.error(f"디렉토리 생성 실패: {str(e)}")
            raise

    def save_report(
        self,
        username: str,
        original_filename: str,
        report_content: str,
    ) -> Dict[str, str]:
        """
        보고서 파일 저장

        파일명 형식: {username}_{년월일시간}_{업로드파일명}_reports.md

        Args:
            username: 사용자 이름 (로그인 ID)
            original_filename: 원본 지도안 파일명
            report_content: 보고서 내용 (Markdown)

        Returns:
            저장된 파일 정보 딕셔너리
            - filename: 저장된 파일명
            - file_path: 저장된 파일 경로
            - timestamp: 저장 시간
        """
        try:
            # 타임스탬프 생성 (년월일시분초)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

            # 원본 파일명에서 확장자 제거
            base_filename = Path(original_filename).stem

            # 파일명 생성: {username}_{년월일시간}_{업로드파일명}_reports.md
            filename = f"{username}_{timestamp}_{base_filename}_reports.md"
            file_path = self.base_dir / filename

            # 파일 저장
            file_path.write_text(report_content, encoding="utf-8")

            logger.info(f"보고서 저장 완료: {filename}")

            return {
                "filename": filename,
                "file_path": str(file_path),
                "timestamp": timestamp,
            }
        except Exception as e:
            logger.error(f"보고서 저장 실패: {str(e)}")
            raise

    def get_report_path(
        self,
        username: str,
        filename: str
    ) -> Optional[str]:
        """
        보고서 파일 경로 반환

        Args:
            username: 사용자 이름 (로그인 ID)
            filename: 파일명

        Returns:
            파일 경로 (존재하지 않으면 None)
        """
        file_path = self.base_dir / filename

        # 파일명이 해당 사용자의 것인지 확인
        if file_path.exists() and filename.startswith(f"{username}_"):
            logger.debug(f"보고서 경로 조회: {file_path}")
            return str(file_path)

        logger.warning(f"보고서 파일 없음 또는 권한 없음: {filename}")
        return None

    def list_reports(self, username: str) -> List[Dict[str, str]]:
        """
        사용자별 보고서 목록 조회

        Args:
            username: 사용자 이름 (로그인 ID)

        Returns:
            보고서 파일 정보 리스트
            - filename: 파일명
            - file_path: 파일 경로
            - size: 파일 크기 (bytes)
            - created_at: 생성 시간
        """
        try:
            pattern = f"{username}_*_reports.md"
            files = list(self.base_dir.glob(pattern))

            reports = []
            for file_path in files:
                stat = file_path.stat()
                reports.append({
                    "filename": file_path.name,
                    "file_path": str(file_path),
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(
                        stat.st_ctime
                    ).isoformat(),
                })

            # 생성 시간 기준 내림차순 정렬 (최신 순)
            reports.sort(key=lambda x: x["created_at"], reverse=True)

            logger.info(f"보고서 목록 조회: username={username}, {len(reports)}개")
            return reports
        except Exception as e:
            logger.error(f"보고서 목록 조회 실패: {str(e)}")
            raise

    def delete_report(
        self,
        username: str,
        filename: str
    ) -> bool:
        """
        보고서 파일 삭제

        Args:
            username: 사용자 이름 (로그인 ID)
            filename: 파일명

        Returns:
            삭제 성공 여부
        """
        try:
            file_path = self.base_dir / filename

            # 파일명이 해당 사용자의 것인지 확인
            if not filename.startswith(f"{username}_"):
                logger.warning(f"삭제 권한 없음: {filename}")
                return False

            if not file_path.exists():
                logger.warning(f"삭제할 파일 없음: {filename}")
                return False

            file_path.unlink()
            logger.info(f"보고서 삭제 완료: {filename}")
            return True
        except Exception as e:
            logger.error(f"보고서 삭제 실패: {str(e)}")
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
            files = list(self.base_dir.glob("*_reports.md"))
            total_size = sum(f.stat().st_size for f in files)

            return {
                "total_files": len(files),
                "total_size": total_size,
            }
        except Exception as e:
            logger.error(f"통계 정보 조회 실패: {str(e)}")
            raise
