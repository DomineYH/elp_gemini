"""초대 코드 서비스"""
import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete

from app.models.invite_codes import InviteCode


class CodeNotFoundError(ValueError):
    """코드를 찾을 수 없음"""
    pass


class CodeAlreadyActiveError(ValueError):
    """이미 활성 상태"""
    pass


class CodeInUseError(ValueError):
    """사용된 코드"""
    pass


class InviteCodeService:
    """초대 코드 서비스 클래스"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _generate_code() -> str:
        """6자리 영숫자 코드 생성"""
        chars = string.ascii_uppercase + string.digits
        return "".join(
            secrets.choice(chars) for _ in range(6)
        )

    async def generate_codes(
        self,
        user_type: str,
        count: int,
        admin_id: int,
    ) -> list[InviteCode]:
        """코드 일괄 생성"""
        codes = []
        for _ in range(count):
            for _retry in range(10):
                code = self._generate_code()
                invite = InviteCode(
                    code=code,
                    user_type=user_type,
                    created_by=admin_id,
                )
                self.db.add(invite)
                try:
                    await self.db.flush()
                    break
                except IntegrityError:
                    await self.db.rollback()
            else:
                raise ValueError(
                    "코드 생성 실패: 중복"
                )
            codes.append(invite)

        for c in codes:
            await self.db.refresh(c)
        return codes

    async def validate_code(
        self, code: str, user_type: str
    ) -> Optional[InviteCode]:
        """코드 유효성 검증"""
        result = await self.db.execute(
            select(InviteCode).where(
                InviteCode.code == code.upper(),
                InviteCode.user_type == user_type,
                InviteCode.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def use_code(
        self, code: str, user_id: int
    ) -> InviteCode:
        """코드에 사용자 연결"""
        result = await self.db.execute(
            select(InviteCode).where(
                InviteCode.code == code.upper()
            )
        )
        invite = result.scalar_one_or_none()
        if not invite:
            raise ValueError(
                "코드를 찾을 수 없습니다"
            )

        invite.user_id = user_id
        invite.used_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(invite)
        return invite

    async def get_codes(
        self,
        user_type: Optional[str] = None,
        status: str = "all",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[InviteCode], int]:
        """코드 목록 조회"""
        query = select(InviteCode)
        count_query = select(
            func.count(InviteCode.id)
        )

        if user_type:
            query = query.where(
                InviteCode.user_type == user_type
            )
            count_query = count_query.where(
                InviteCode.user_type == user_type
            )

        if status == "used":
            cond = InviteCode.user_id.isnot(None)
            query = query.where(cond)
            count_query = count_query.where(cond)
        elif status == "unused":
            cond_unused = InviteCode.user_id.is_(None)
            cond_active = InviteCode.is_active.is_(
                True
            )
            query = query.where(
                cond_unused, cond_active
            )
            count_query = count_query.where(
                cond_unused, cond_active
            )
        elif status == "inactive":
            cond = InviteCode.is_active.is_(False)
            query = query.where(cond)
            count_query = count_query.where(cond)

        total_result = await self.db.execute(
            count_query
        )
        total = total_result.scalar()

        offset = (page - 1) * page_size
        query = (
            query.order_by(
                InviteCode.created_at.desc()
            )
            .offset(offset)
            .limit(page_size)
        )

        result = await self.db.execute(query)
        codes = list(result.scalars().all())

        return codes, total

    async def deactivate_code(
        self, code_id: int
    ) -> InviteCode:
        """코드 비활성화"""
        result = await self.db.execute(
            select(InviteCode).where(
                InviteCode.id == code_id
            )
        )
        invite = result.scalar_one_or_none()
        if not invite:
            raise CodeNotFoundError(
                "코드를 찾을 수 없습니다"
            )

        invite.is_active = False
        await self.db.flush()
        await self.db.refresh(invite)
        return invite

    async def activate_code(
        self, code_id: int
    ) -> InviteCode:
        """비활성화된 코드 재활성화"""
        result = await self.db.execute(
            select(InviteCode).where(
                InviteCode.id == code_id
            )
        )
        invite = result.scalar_one_or_none()
        if not invite:
            raise CodeNotFoundError(
                "코드를 찾을 수 없습니다"
            )
        if invite.is_active:
            raise CodeAlreadyActiveError(
                "이미 활성 상태입니다"
            )

        invite.is_active = True
        await self.db.flush()
        await self.db.refresh(invite)
        return invite

    async def delete_code(
        self, code_id: int
    ) -> None:
        """코드 영구 삭제 (미사용 코드만, atomic)"""
        result = await self.db.execute(
            select(InviteCode).where(
                InviteCode.id == code_id
            )
        )
        invite = result.scalar_one_or_none()
        if not invite:
            raise CodeNotFoundError(
                "코드를 찾을 수 없습니다"
            )
        if invite.user_id is not None:
            raise CodeInUseError(
                "사용된 코드는 삭제할 수 없습니다"
            )

        # Atomic delete: 조건부 삭제로 race condition 방지
        del_result = await self.db.execute(
            delete(InviteCode).where(
                InviteCode.id == code_id,
                InviteCode.user_id.is_(None),
            )
        )
        if del_result.rowcount == 0:
            raise CodeInUseError(
                "사용된 코드는 삭제할 수 없습니다"
            )
        await self.db.flush()

    async def get_stats(self) -> list[dict]:
        """유형별 코드 통계"""
        result = await self.db.execute(
            select(
                InviteCode.user_type,
                func.count(InviteCode.id).label(
                    "total"
                ),
                func.count(
                    InviteCode.user_id
                ).label("used"),
            )
            .where(InviteCode.is_active.is_(True))
            .group_by(InviteCode.user_type)
        )
        stats = []
        for row in result.all():
            stats.append(
                {
                    "user_type": row[0],
                    "total": row[1],
                    "used": row[2],
                    "unused": row[1] - row[2],
                }
            )
        return stats
