"""관리자용 삭제 서비스.

사용자/대화/보고서의 hard delete와 연관 파일 정리를 담당한다.
모든 권한·CSRF 검증은 호출 측(라우터)에서 처리한다.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_reports import AnalysisReport
from app.models.users import User
from app.services.admin_export_service import LESSONPLAN_BASE_DIR
from app.utils.logging import log_user_action

logger = logging.getLogger(__name__)


class AdminDeletionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ----- 사용자 -----
    async def delete_user(
        self,
        target_user_id: int,
        current_admin_id: int,
    ) -> dict[str, Any]:
        if target_user_id == current_admin_id:
            raise PermissionError("자기 자신은 삭제할 수 없습니다.")

        result = await self.db.execute(
            select(User).where(User.id == target_user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise LookupError("사용자를 찾을 수 없습니다.")
        if user.is_admin:
            raise PermissionError("관리자 계정은 삭제할 수 없습니다.")

        # 파일 정리를 위해 보고서 목록을 먼저 수집
        reports_result = await self.db.execute(
            select(AnalysisReport).where(
                AnalysisReport.user_id == target_user_id
            )
        )
        reports = list(reports_result.scalars().all())

        # DB 삭제 — relationship cascade가 세션/메시지/프로필 처리
        await self.db.delete(user)
        await self.db.commit()

        files_removed = self._remove_report_files(reports)

        log_user_action(
            user_id=current_admin_id,
            action="admin_user_delete",
            details={
                "target_user_id": target_user_id,
                "files_removed": files_removed,
            },
            success=True,
        )
        return {"ok": True, "deleted": 1, "files_removed": files_removed}

    # ----- 파일 정리 헬퍼 -----
    def _resolve_lessonplan_path(
        self, raw: str | None
    ) -> Path | None:
        """lessonplan_filename을 실제 파일 경로로 해석한다.

        프로덕션에서는 bare filename으로 저장되므로 base dir과 결합한다.
        절대 경로로 저장된 레거시 행은 그대로 사용한다.
        """
        if not raw:
            return None
        path = Path(raw)
        if path.is_absolute():
            return path
        return Path(LESSONPLAN_BASE_DIR) / raw

    def _remove_report_files(
        self, reports: list[AnalysisReport]
    ) -> int:
        """report_path(.md) + lessonplan_filename(.pdf) 삭제.

        실제로 존재할 때만 삭제하여 오삭제를 방지한다.
        """
        removed = 0
        for report in reports:
            candidates: list[Path | None] = [
                Path(report.report_path) if report.report_path else None,
                self._resolve_lessonplan_path(report.lessonplan_filename),
            ]
            for path in candidates:
                if path is None or not path.exists():
                    continue
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:
                    logger.warning(
                        "파일 삭제 실패: path=%s, err=%s", path, exc
                    )
        return removed
