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
from app.models.chat_sessions import ChatSession
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

        # 파일 정리를 위해 보고서 목록과 username을 먼저 수집
        reports_result = await self.db.execute(
            select(AnalysisReport).where(
                AnalysisReport.user_id == target_user_id
            )
        )
        reports = list(reports_result.scalars().all())
        username = user.username

        # DB 삭제 — relationship cascade가 세션/메시지/프로필 처리
        await self.db.delete(user)
        await self.db.commit()

        md_count = self._remove_report_md_files(reports)
        upload_count = self._remove_user_upload_files(username)
        files_removed = md_count + upload_count

        log_user_action(
            user_id=current_admin_id,
            action="admin_user_delete",
            details={
                "target_user_id": target_user_id,
                "md_files_removed": md_count,
                "upload_files_removed": upload_count,
            },
            success=True,
        )
        return {"ok": True, "deleted": 1, "files_removed": files_removed}

    # ----- 대화 세션 -----
    async def delete_chat_session(
        self,
        session_id: int,
        current_admin_id: int,
    ) -> dict[str, Any]:
        result = await self.db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise LookupError("대화 세션을 찾을 수 없습니다.")

        await self.db.delete(session)  # cascade: messages
        await self.db.commit()

        log_user_action(
            user_id=current_admin_id,
            action="admin_chat_session_delete",
            details={"session_id": session_id},
            success=True,
        )
        return {"ok": True, "deleted": 1, "files_removed": 0}

    # ----- 분석 보고서 -----
    async def delete_analysis_report(
        self,
        report_id: int,
        current_admin_id: int,
    ) -> dict[str, Any]:
        result = await self.db.execute(
            select(AnalysisReport).where(AnalysisReport.id == report_id)
        )
        report = result.scalar_one_or_none()
        if report is None:
            raise LookupError("분석 보고서를 찾을 수 없습니다.")

        # delete_user와 동일 순서: DB commit 먼저, 그 다음 파일 제거.
        # 파일 제거가 실패해도 고아 DB 행이 남지 않도록 한다
        # (expire_on_commit=False라 in-memory 속성은 commit 후에도 유효).
        reports_snapshot = [report]

        await self.db.delete(report)
        await self.db.commit()

        files_removed = self._remove_report_md_files(reports_snapshot)

        log_user_action(
            user_id=current_admin_id,
            action="admin_analysis_report_delete",
            details={
                "report_id": report_id,
                "files_removed": files_removed,
            },
            success=True,
        )
        return {
            "ok": True,
            "deleted": 1,
            "files_removed": files_removed,
        }

    # ----- bulk -----
    async def bulk_delete_sessions(
        self,
        user_id: int,
        session_ids: list[int],
        current_admin_id: int,
    ) -> dict[str, Any]:
        if not session_ids:
            return {"ok": True, "deleted": 0, "files_removed": 0}

        # dedup, preserve insertion order (audit log 가독성 유지)
        session_ids = list(dict.fromkeys(session_ids))

        rows = await self.db.execute(
            select(ChatSession).where(ChatSession.id.in_(session_ids))
        )
        sessions = list(rows.scalars().all())

        # 모든 세션이 user_id에 속해야 한다
        bad = [s.id for s in sessions if s.user_id != user_id]
        if len(sessions) != len(session_ids) or bad:
            raise ValueError(
                "요청한 세션 중 일부가 해당 사용자 소유가 아니거나 존재하지 않습니다."
            )

        for session in sessions:
            await self.db.delete(session)
        await self.db.commit()

        log_user_action(
            user_id=current_admin_id,
            action="admin_chat_session_bulk_delete",
            details={
                "target_user_id": user_id,
                "session_ids": session_ids,
            },
            success=True,
        )
        return {
            "ok": True,
            "deleted": len(sessions),
            "files_removed": 0,
        }

    async def bulk_delete_reports(
        self,
        user_id: int,
        report_ids: list[int],
        current_admin_id: int,
    ) -> dict[str, Any]:
        if not report_ids:
            return {"ok": True, "deleted": 0, "files_removed": 0}

        # dedup, preserve insertion order (audit log 가독성 유지)
        report_ids = list(dict.fromkeys(report_ids))

        rows = await self.db.execute(
            select(AnalysisReport).where(
                AnalysisReport.id.in_(report_ids)
            )
        )
        reports = list(rows.scalars().all())

        bad = [r.id for r in reports if r.user_id != user_id]
        if len(reports) != len(report_ids) or bad:
            raise ValueError(
                "요청한 보고서 중 일부가 해당 사용자 소유가 아니거나 존재하지 않습니다."
            )

        # delete_user와 동일 순서: DB commit 먼저, 그 다음 파일 제거.
        # expire_on_commit=False라 in-memory 속성은 commit 후에도 유효하다.
        reports_snapshot = list(reports)

        for report in reports:
            await self.db.delete(report)
        await self.db.commit()

        files_removed = self._remove_report_md_files(reports_snapshot)

        log_user_action(
            user_id=current_admin_id,
            action="admin_analysis_report_bulk_delete",
            details={
                "target_user_id": user_id,
                "report_ids": report_ids,
                "files_removed": files_removed,
            },
            success=True,
        )
        return {
            "ok": True,
            "deleted": len(reports),
            "files_removed": files_removed,
        }

    # ----- 파일 정리 헬퍼 -----
    def _remove_report_md_files(
        self, reports: list[AnalysisReport]
    ) -> int:
        """report_path(.md) 파일만 삭제한다.

        실제로 존재할 때만 삭제하여 오삭제를 방지한다.
        """
        removed = 0
        for report in reports:
            if not report.report_path:
                continue
            path = Path(report.report_path)
            if not path.exists():
                continue
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                logger.warning(
                    "파일 삭제 실패: path=%s, err=%s", path, exc
                )
        return removed

    def _remove_user_upload_files(self, username: str) -> int:
        """사용자 prefix로 저장된 업로드 파일을 삭제한다."""
        removed = 0
        base_dir = Path(LESSONPLAN_BASE_DIR)
        try:
            files = list(base_dir.iterdir())
        except OSError as exc:
            logger.warning(
                "업로드 파일 목록 조회 실패: path=%s, err=%s",
                base_dir,
                exc,
            )
            return removed

        prefix = f"{username}_"
        for path in files:
            if (
                not path.name.startswith(prefix)
                or path.is_symlink()
                or not path.is_file()
            ):
                continue
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                logger.warning(
                    "파일 삭제 실패: path=%s, err=%s", path, exc
                )
        return removed
