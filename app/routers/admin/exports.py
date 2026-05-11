# app/routers/admin/exports.py
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_admin
from app.models.users import User
from app.schemas.admin_export import ExportFilters, parse_filters
from app.services.admin_export_service import AdminExportService


router = APIRouter(tags=["admin-exports"])


@router.get("/admin/api/exports/all.zip")
async def export_all(
    filters: ExportFilters = Depends(parse_filters),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    service = AdminExportService(db)
    plan = await service.collect(filters)
    filename = (
        f"elp_export_{datetime.utcnow():%Y%m%d_%H%M%S}.zip"
    )
    return StreamingResponse(
        service.stream_zip(plan),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            ),
        },
    )
