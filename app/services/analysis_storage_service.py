"""
분석 결과 마크다운 파일 저장 서비스
data/analys/ 디렉토리에 사용자별 분석 결과 관리
"""
import os
import logging
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class AnalysisStorageService:
    """분석 결과 마크다운 파일 저장 서비스"""

    def __init__(self, base_dir: str = "data/analys"):
        """
        서비스 초기화

        Args:
            base_dir: 분석 결과 저장 기본 디렉토리
        """
        self.base_dir = Path(base_dir)
        self._ensure_directory_exists()

    def _ensure_directory_exists(self) -> None:
        """저장 디렉토리 존재 확인 및 생성"""
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"분석 결과 디렉토리 확인: {self.base_dir}")
        except Exception as e:
            logger.error(f"디렉토리 생성 실패: {str(e)}")
            raise

    def _generate_markdown_header(
        self,
        username: str,
        lessonplan_filename: str,
        evaluation_type: str = "general",
    ) -> str:
        """
        마크다운 헤더 자동 생성

        Args:
            username: 사용자 이름
            lessonplan_filename: 지도안 파일명
            evaluation_type: 평가 유형

        Returns:
            마크다운 헤더 문자열
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = f"""# 수업 지도안 분석 결과

## 메타데이터
- **사용자**: {username}
- **지도안 파일**: {lessonplan_filename}
- **평가 유형**: {evaluation_type}
- **분석 일시**: {timestamp}

---

"""
        return header

    def save_analysis(
        self,
        username: str,
        lessonplan_filename: str,
        analysis_content: str,
        evaluation_type: str = "general",
    ) -> Dict[str, str]:
        """
        분석 결과 저장

        Args:
            username: 사용자 이름
            lessonplan_filename: 지도안 파일명
            analysis_content: 분석 내용
            evaluation_type: 평가 유형

        Returns:
            저장된 파일 정보 딕셔너리
            - file_path: 저장된 파일 경로
            - filename: 저장된 파일명
            - timestamp: 저장 시간
        """
        try:
            # 파일명 생성: {username}_{지도안파일명}.md
            # 지도안 파일명에서 확장자 제거
            base_name = Path(lessonplan_filename).stem
            filename = f"{username}_{base_name}.md"
            file_path = self.base_dir / filename

            # 마크다운 헤더 생성
            header = self._generate_markdown_header(
                username, lessonplan_filename, evaluation_type
            )

            # 전체 내용 구성
            full_content = header + analysis_content

            # 파일 저장
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(full_content)

            logger.info(f"분석 결과 저장 완료: {filename}")

            return {
                "file_path": str(file_path),
                "filename": filename,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"분석 결과 저장 실패: {str(e)}")
            raise

    def get_analysis(
        self, username: str, lessonplan_filename: str
    ) -> Optional[str]:
        """
        분석 결과 읽기

        Args:
            username: 사용자 이름
            lessonplan_filename: 지도안 파일명

        Returns:
            분석 결과 내용 (존재하지 않으면 None)
        """
        try:
            # 파일명 생성
            base_name = Path(lessonplan_filename).stem
            filename = f"{username}_{base_name}.md"
            file_path = self.base_dir / filename

            if not file_path.exists():
                logger.warning(f"분석 결과 파일 없음: {filename}")
                return None

            # 파일 읽기
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            logger.debug(f"분석 결과 조회: {filename}")
            return content
        except Exception as e:
            logger.error(f"분석 결과 조회 실패: {str(e)}")
            raise

    def list_analyses(self, username: str) -> List[Dict[str, str]]:
        """
        사용자별 분석 결과 목록 조회

        Args:
            username: 사용자 이름

        Returns:
            분석 결과 파일 정보 리스트
            - filename: 파일명
            - lessonplan_filename: 지도안 파일명
            - file_path: 파일 경로
            - size: 파일 크기 (bytes)
            - created_at: 생성 시간
        """
        try:
            pattern = f"{username}_*.md"
            files = list(self.base_dir.glob(pattern))

            analyses = []
            for file_path in files:
                # 지도안 파일명 추출
                # {username}_{lessonplan}.md → {lessonplan}
                name_without_ext = file_path.stem
                lessonplan = name_without_ext.replace(
                    f"{username}_", "", 1
                )

                # 파일 정보 수집
                stat = file_path.stat()
                analyses.append(
                    {
                        "filename": file_path.name,
                        "lessonplan_filename": lessonplan,
                        "file_path": str(file_path),
                        "size": stat.st_size,
                        "created_at": datetime.fromtimestamp(
                            stat.st_ctime
                        ).isoformat(),
                    }
                )

            logger.info(
                f"분석 결과 목록 조회: {username}, "
                f"{len(analyses)}개"
            )
            return analyses
        except Exception as e:
            logger.error(f"분석 결과 목록 조회 실패: {str(e)}")
            raise

    def delete_analysis(
        self, username: str, lessonplan_filename: str
    ) -> bool:
        """
        분석 결과 삭제

        Args:
            username: 사용자 이름
            lessonplan_filename: 지도안 파일명

        Returns:
            삭제 성공 여부
        """
        try:
            # 파일명 생성
            base_name = Path(lessonplan_filename).stem
            filename = f"{username}_{base_name}.md"
            file_path = self.base_dir / filename

            if not file_path.exists():
                logger.warning(f"삭제할 파일 없음: {filename}")
                return False

            file_path.unlink()
            logger.info(f"분석 결과 삭제 완료: {filename}")
            return True
        except Exception as e:
            logger.error(f"분석 결과 삭제 실패: {str(e)}")
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
            files = list(self.base_dir.glob("*.md"))
            total_size = sum(f.stat().st_size for f in files)

            return {
                "total_files": len(files),
                "total_size": total_size,
            }
        except Exception as e:
            logger.error(f"통계 정보 조회 실패: {str(e)}")
            raise
