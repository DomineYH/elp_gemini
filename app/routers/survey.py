"""설문 참여 완료 기록 라우터 (자가 확인, 사용자당 1회)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.users import User

router = APIRouter(prefix="/api/survey", tags=["survey"])


@router.post("/complete")
async def complete_survey(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """참여 설문 완료를 기록한다. 이미 완료면 그대로(멱등)."""
    if current_user.survey_completed_at is None:
        current_user.survey_completed_at = datetime.now(timezone.utc)
        db.add(current_user)
        await db.commit()
    return {"success": True, "survey_completed": True}
