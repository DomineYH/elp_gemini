"""
시뮬레이션이 쓰는 '현재 지도안' = 사용자의 최신 업로드 행과 그 PDF 텍스트
"""

import re
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lessonplan_uploads import LessonPlanUpload

UPLOADS_DIR = Path("app/static/uploads")
# PDF 글머리 기호 글꼴 등의 사설 영역 글자는 깨진 기호로 보인다 (#391)
PRIVATE_USE = re.compile("[\ue000-\uf8ff]")


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


async def get_store_ids(db: AsyncSession, user_id: int) -> list[str]:
    """사용자의 업로드 행들이 가리키는 File Search 스토어 id (#470).

    사용자 스토어는 이 id 로만 지운다. 표시 이름으로는 찾지 않는다.
    """
    result = await db.scalars(
        select(LessonPlanUpload.fs_store_id)
        .where(
            LessonPlanUpload.user_id == user_id,
            LessonPlanUpload.fs_store_id.is_not(None),
        )
        .distinct()
    )
    return [store_id for store_id in result if store_id]


async def forget_file_search_ids(db: AsyncSession, user_id: int) -> None:
    """사용자 File Search 스토어 삭제 뒤 업로드 행의 문서 ID를 비운다 (#173)."""
    await db.execute(
        update(LessonPlanUpload)
        .where(LessonPlanUpload.user_id == user_id)
        .values(fs_document_id=None, fs_store_id=None)
    )
    await db.commit()


def extract_text(upload: LessonPlanUpload) -> str:
    """추출 텍스트는 DB에 없으므로 저장된 PDF를 다시 읽는다. 파일 없음 → ""."""
    path = UPLOADS_DIR / str(upload.user_id) / upload.filename
    if not path.is_file():
        return ""
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    # pypdf가 일부 PDF의 낱말 사이 공백을 NUL로 돌려준다 (#391)
    return PRIVATE_USE.sub("", text.replace("\x00", " "))
