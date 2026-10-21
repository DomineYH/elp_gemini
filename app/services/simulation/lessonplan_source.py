"""
시뮬레이션이 쓰는 '현재 지도안' = 사용자의 최신 업로드 행과 그 PDF 텍스트
"""

from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lessonplan_uploads import LessonPlanUpload

UPLOADS_DIR = Path("app/static/uploads")


async def get_latest_upload(
    db: AsyncSession, user_id: int
) -> LessonPlanUpload | None:
    # lessonplan_analysis_service와 같은 정렬
    result = await db.execute(
        select(LessonPlanUpload)
        .where(LessonPlanUpload.user_id == user_id)
        .order_by(
            LessonPlanUpload.created_at.desc(),
            LessonPlanUpload.id.desc(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


def extract_text(upload: LessonPlanUpload) -> str:
    """추출 텍스트는 DB에 없으므로 저장된 PDF를 다시 읽는다. 파일 없음 → ""."""
    path = UPLOADS_DIR / str(upload.user_id) / upload.filename
    if not path.is_file():
        return ""
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)
