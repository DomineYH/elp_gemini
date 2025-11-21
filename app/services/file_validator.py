"""
파일 검증 서비스
업로드된 파일의 보안 및 유효성 검증
"""
import re
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
from fastapi import UploadFile, HTTPException

logger = logging.getLogger(__name__)


class FileValidator:
    """파일 보안 및 유효성 검증"""

    # 허용된 PDF MIME types
    ALLOWED_PDF_MIMES = {
        "application/pdf",
        "application/x-pdf",
    }

    # PDF 헤더 시그니처
    PDF_HEADER_PATTERN = rb"^%PDF-\d\.\d"

    # 최대 파일 크기 (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024

    # 의심스러운 PDF 내용 패턴
    SUSPICIOUS_PATTERNS = [
        rb"/JavaScript",
        rb"/JS",
        rb"/Launch",
        rb"/EmbeddedFile",
        rb"/OpenAction",
        rb"/AA",  # Additional Actions
        rb"/Names",
    ]

    def __init__(self, max_size_mb: Optional[int] = None):
        """
        초기화

        Args:
            max_size_mb: 최대 파일 크기 (MB)
        """
        if max_size_mb:
            self.max_file_size = max_size_mb * 1024 * 1024
        else:
            self.max_file_size = self.MAX_FILE_SIZE

    def validate_pdf(
        self, file: UploadFile, contents: bytes
    ) -> Tuple[int, Dict[str, str]]:
        """
        PDF 파일 종합 검증

        Args:
            file: 업로드 파일 객체
            contents: 파일 내용 (바이트)

        Returns:
            (파일 크기, 메타데이터)

        Raises:
            HTTPException: 검증 실패 시
        """
        # 1. MIME type 검증
        self._validate_mime_type(file)

        # 2. 파일 크기 검증
        file_size = self._validate_file_size(contents)

        # 3. PDF 헤더 검증
        self._validate_pdf_header(contents)

        # 4. 악성 콘텐츠 검사
        warnings = self._scan_suspicious_content(contents)

        # 5. 메타데이터 추출
        metadata = self._extract_metadata(contents, warnings)

        logger.info(
            f"파일 검증 완료: "
            f"size={file_size}, warnings={len(warnings)}"
        )

        return file_size, metadata

    def _validate_mime_type(self, file: UploadFile) -> None:
        """MIME type 검증"""
        if file.content_type not in self.ALLOWED_PDF_MIMES:
            logger.warning(
                f"잘못된 MIME type: {file.content_type}"
            )
            raise HTTPException(
                status_code=400,
                detail="PDF 파일만 업로드 가능합니다",
            )

    def _validate_file_size(self, contents: bytes) -> int:
        """파일 크기 검증"""
        file_size = len(contents)

        if file_size == 0:
            raise HTTPException(
                status_code=400,
                detail="빈 파일은 업로드할 수 없습니다",
            )

        if file_size > self.max_file_size:
            max_mb = self.max_file_size / (1024 * 1024)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"파일 크기는 {max_mb:.0f}MB를 "
                    "초과할 수 없습니다"
                ),
            )

        return file_size

    def _validate_pdf_header(self, contents: bytes) -> None:
        """PDF 헤더 검증"""
        # PDF는 반드시 %PDF-x.y로 시작해야 함
        if not re.match(self.PDF_HEADER_PATTERN, contents[:8]):
            logger.warning("잘못된 PDF 헤더")
            raise HTTPException(
                status_code=400,
                detail="유효하지 않은 PDF 파일입니다",
            )

        # PDF 버전 추출 및 검증
        version_match = re.search(
            rb"%PDF-(\d)\.(\d)", contents[:20]
        )
        if version_match:
            major, minor = (
                int(version_match.group(1)),
                int(version_match.group(2)),
            )
            if major > 2 or (major == 2 and minor > 0):
                logger.warning(
                    f"높은 PDF 버전: {major}.{minor}"
                )

    def _scan_suspicious_content(
        self, contents: bytes
    ) -> list[str]:
        """악성 콘텐츠 패턴 검사"""
        warnings = []

        for pattern in self.SUSPICIOUS_PATTERNS:
            if re.search(pattern, contents, re.IGNORECASE):
                pattern_str = pattern.decode("utf-8", errors="ignore")
                warnings.append(f"의심 패턴: {pattern_str}")
                logger.warning(f"의심스러운 패턴 감지: {pattern_str}")

        # JavaScript 포함 여부 특별 검사
        if re.search(rb"/JavaScript|/JS", contents, re.IGNORECASE):
            logger.warning("JavaScript 포함된 PDF 감지 (업로드 허용됨)")
            warnings.append("JavaScript 포함됨")

        # Launch 액션 검사 (외부 프로그램 실행)
        if re.search(rb"/Launch", contents, re.IGNORECASE):
            logger.warning("Launch 액션 포함된 PDF 감지")
            raise HTTPException(
                status_code=400,
                detail=(
                    "외부 프로그램 실행이 포함된 PDF는 "
                    "업로드할 수 없습니다"
                ),
            )

        return warnings

    def _extract_metadata(
        self, contents: bytes, warnings: list[str]
    ) -> Dict[str, str]:
        """
        메타데이터 추출

        Args:
            contents: 파일 내용
            warnings: 경고 목록

        Returns:
            메타데이터 딕셔너리
        """
        metadata = {}

        # PDF 버전
        version_match = re.search(
            rb"%PDF-(\d\.\d)", contents[:20]
        )
        if version_match:
            metadata["pdf_version"] = version_match.group(
                1
            ).decode("ascii")

        # 페이지 수 추정 (정확하지 않을 수 있음)
        page_matches = re.findall(rb"/Type\s*/Page[^s]", contents)
        if page_matches:
            metadata["estimated_pages"] = str(len(page_matches))

        # 경고 정보
        if warnings:
            metadata["warnings"] = ", ".join(warnings)

        # 검증 상태
        metadata["validated"] = "true"
        metadata["validation_passed"] = (
            "true" if not warnings else "with_warnings"
        )

        return metadata


# 싱글톤 인스턴스
_file_validator = FileValidator()


def get_file_validator() -> FileValidator:
    """
    FileValidator 싱글톤 반환

    Returns:
        FileValidator 인스턴스
    """
    return _file_validator
