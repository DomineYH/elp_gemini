"""
초대 코드 서비스 테스트
코드 생성, 검증, 사용, 조회, 비활성화, 활성화, 삭제, 통계
"""
import pytest
import pytest_asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invite_codes import InviteCode
from app.models.users import User
from app.services.invite_code_service import (
    InviteCodeService,
    CodeNotFoundError,
    CodeAlreadyActiveError,
    CodeInUseError,
)
from tests.conftest import (
    TestingSessionLocal,
    engine,
)
from app.db import Base


@pytest_asyncio.fixture
async def setup_db():
    """DB 테이블 생성/삭제"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session(setup_db):
    """DB 세션 픽스처"""
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession):
    """관리자 사용자 픽스처"""
    user = User(
        username="admin",
        nickname="Admin",
        email="admin@test.com",
        hashed_password="hashed",
        is_admin=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def normal_user(db_session: AsyncSession):
    """일반 사용자 픽스처"""
    user = User(
        username="student1",
        nickname="Student1",
        email="student@test.com",
        hashed_password="hashed",
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


class TestGenerateCodes:
    """코드 생성 테스트"""

    @pytest.mark.asyncio
    async def test_generate_single_code(
        self, db_session: AsyncSession, admin_user: User
    ):
        """단일 코드 생성"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="1학년", count=1, admin_id=admin_user.id
        )
        await db_session.commit()

        assert len(codes) == 1
        assert codes[0].code.isalnum()
        assert len(codes[0].code) == 6
        assert codes[0].user_type == "1학년"
        assert codes[0].created_by == admin_user.id
        assert codes[0].is_active is True
        assert codes[0].user_id is None

    @pytest.mark.asyncio
    async def test_generate_multiple_codes(
        self, db_session: AsyncSession, admin_user: User
    ):
        """여러 코드 일괄 생성"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="2학년", count=5, admin_id=admin_user.id
        )
        await db_session.commit()

        assert len(codes) == 5
        code_values = [c.code for c in codes]
        assert len(set(code_values)) == 5  # 모두 고유

    @pytest.mark.asyncio
    async def test_generate_codes_are_uppercase(
        self, db_session: AsyncSession, admin_user: User
    ):
        """코드는 대문자+숫자 조합"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="3학년", count=10, admin_id=admin_user.id
        )
        await db_session.commit()

        for code in codes:
            assert code.code.isupper() or code.code.isdigit()


class TestValidateCode:
    """코드 검증 테스트"""

    @pytest.mark.asyncio
    async def test_validate_valid_code(
        self, db_session: AsyncSession, admin_user: User
    ):
        """유효한 코드 검증"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="1학년", count=1, admin_id=admin_user.id
        )
        await db_session.commit()

        result = await service.validate_code(
            codes[0].code, "1학년"
        )
        assert result is not None
        assert result.code == codes[0].code

    @pytest.mark.asyncio
    async def test_validate_invalid_code(
        self, db_session: AsyncSession
    ):
        """존재하지 않는 코드 검증"""
        service = InviteCodeService(db_session)
        result = await service.validate_code(
            "ZZZZZZ", "1학년"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_code_wrong_type(
        self, db_session: AsyncSession, admin_user: User
    ):
        """잘못된 user_type으로 검증"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="1학년", count=1, admin_id=admin_user.id
        )
        await db_session.commit()

        result = await service.validate_code(
            codes[0].code, "2학년"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_code_case_insensitive(
        self, db_session: AsyncSession, admin_user: User
    ):
        """코드 대소문자 구분 없음"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="1학년", count=1, admin_id=admin_user.id
        )
        await db_session.commit()

        result = await service.validate_code(
            codes[0].code.lower(), "1학년"
        )
        assert result is not None


class TestUseCode:
    """코드 사용 테스트"""

    @pytest.mark.asyncio
    async def test_use_code_success(
        self,
        db_session: AsyncSession,
        admin_user: User,
        normal_user: User,
    ):
        """코드 사용 성공"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="1학년", count=1, admin_id=admin_user.id
        )
        await db_session.commit()

        used = await service.use_code(
            codes[0].code, normal_user.id
        )
        await db_session.commit()

        assert used.user_id == normal_user.id
        assert used.used_at is not None

    @pytest.mark.asyncio
    async def test_use_nonexistent_code(
        self, db_session: AsyncSession, normal_user: User
    ):
        """존재하지 않는 코드 사용 시 예외"""
        service = InviteCodeService(db_session)
        with pytest.raises(ValueError) as exc:
            await service.use_code(
                "ZZZZZZ", normal_user.id
            )
        assert "찾을 수 없습니다" in str(exc.value)


class TestGetCodes:
    """코드 목록 조회 테스트"""

    @pytest.mark.asyncio
    async def test_get_all_codes(
        self, db_session: AsyncSession, admin_user: User
    ):
        """전체 코드 조회"""
        service = InviteCodeService(db_session)
        await service.generate_codes(
            user_type="1학년", count=3, admin_id=admin_user.id
        )
        await service.generate_codes(
            user_type="2학년", count=2, admin_id=admin_user.id
        )
        await db_session.commit()

        codes, total = await service.get_codes()
        assert total == 5
        assert len(codes) == 5

    @pytest.mark.asyncio
    async def test_get_codes_by_user_type(
        self, db_session: AsyncSession, admin_user: User
    ):
        """user_type 필터링"""
        service = InviteCodeService(db_session)
        await service.generate_codes(
            user_type="1학년", count=3, admin_id=admin_user.id
        )
        await service.generate_codes(
            user_type="2학년", count=2, admin_id=admin_user.id
        )
        await db_session.commit()

        codes, total = await service.get_codes(
            user_type="1학년"
        )
        assert total == 3
        for c in codes:
            assert c.user_type == "1학년"

    @pytest.mark.asyncio
    async def test_get_codes_pagination(
        self, db_session: AsyncSession, admin_user: User
    ):
        """페이지네이션"""
        service = InviteCodeService(db_session)
        await service.generate_codes(
            user_type="1학년", count=25, admin_id=admin_user.id
        )
        await db_session.commit()

        codes, total = await service.get_codes(
            page=1, page_size=10
        )
        assert total == 25
        assert len(codes) == 10

        codes2, _ = await service.get_codes(page=2, page_size=10)
        assert len(codes2) == 10

    @pytest.mark.asyncio
    async def test_get_codes_status_filter(
        self,
        db_session: AsyncSession,
        admin_user: User,
        normal_user: User,
    ):
        """상태 필터링"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="1학년", count=3, admin_id=admin_user.id
        )
        await db_session.commit()

        # 하나 사용
        await service.use_code(codes[0].code, normal_user.id)
        # 하나 비활성화
        await service.deactivate_code(codes[1].id)
        await db_session.commit()

        # used
        used, used_cnt = await service.get_codes(status="used")
        assert used_cnt == 1

        # unused
        unused, unused_cnt = await service.get_codes(
            status="unused"
        )
        assert unused_cnt == 1

        # inactive
        inactive, inactive_cnt = await service.get_codes(
            status="inactive"
        )
        assert inactive_cnt == 1


class TestDeactivateCode:
    """코드 비활성화 테스트"""

    @pytest.mark.asyncio
    async def test_deactivate_success(
        self, db_session: AsyncSession, admin_user: User
    ):
        """비활성화 성공"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="1학년", count=1, admin_id=admin_user.id
        )
        await db_session.commit()

        result = await service.deactivate_code(codes[0].id)
        await db_session.commit()

        assert result.is_active is False

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent(
        self, db_session: AsyncSession
    ):
        """존재하지 않는 코드 비활성화 시 예외"""
        service = InviteCodeService(db_session)
        with pytest.raises(ValueError) as exc:
            await service.deactivate_code(99999)
        assert "찾을 수 없습니다" in str(exc.value)


class TestActivateCode:
    """코드 활성화 테스트"""

    @pytest.mark.asyncio
    async def test_activate_success(
        self, db_session: AsyncSession, admin_user: User
    ):
        """비활성 코드 활성화 성공"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="1학년",
            count=1,
            admin_id=admin_user.id,
        )
        await db_session.commit()

        await service.deactivate_code(codes[0].id)
        await db_session.commit()
        assert codes[0].is_active is False

        result = await service.activate_code(
            codes[0].id
        )
        await db_session.commit()
        assert result.is_active is True

    @pytest.mark.asyncio
    async def test_activate_already_active(
        self, db_session: AsyncSession, admin_user: User
    ):
        """이미 활성인 코드 활성화 시 예외"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="1학년",
            count=1,
            admin_id=admin_user.id,
        )
        await db_session.commit()

        with pytest.raises(CodeAlreadyActiveError):
            await service.activate_code(codes[0].id)

    @pytest.mark.asyncio
    async def test_activate_nonexistent(
        self, db_session: AsyncSession
    ):
        """존재하지 않는 코드 활성화 시 예외"""
        service = InviteCodeService(db_session)
        with pytest.raises(CodeNotFoundError):
            await service.activate_code(99999)


class TestDeleteCode:
    """코드 삭제 테스트"""

    @pytest.mark.asyncio
    async def test_delete_unused_code(
        self, db_session: AsyncSession, admin_user: User
    ):
        """미사용 코드 삭제 성공"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="1학년",
            count=1,
            admin_id=admin_user.id,
        )
        await db_session.commit()

        code_id = codes[0].id
        await service.delete_code(code_id)
        await db_session.commit()

        remaining, total = await service.get_codes()
        assert total == 0

    @pytest.mark.asyncio
    async def test_delete_used_code_raises(
        self,
        db_session: AsyncSession,
        admin_user: User,
        normal_user: User,
    ):
        """사용된 코드 삭제 시 예외"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="1학년",
            count=1,
            admin_id=admin_user.id,
        )
        await db_session.commit()

        await service.use_code(
            codes[0].code, normal_user.id
        )
        await db_session.commit()

        with pytest.raises(CodeInUseError):
            await service.delete_code(codes[0].id)

    @pytest.mark.asyncio
    async def test_delete_inactive_unused_code(
        self, db_session: AsyncSession, admin_user: User
    ):
        """비활성+미사용 코드 삭제 성공"""
        service = InviteCodeService(db_session)
        codes = await service.generate_codes(
            user_type="1학년",
            count=1,
            admin_id=admin_user.id,
        )
        await db_session.commit()

        await service.deactivate_code(codes[0].id)
        await db_session.commit()

        await service.delete_code(codes[0].id)
        await db_session.commit()

        _, total = await service.get_codes()
        assert total == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent(
        self, db_session: AsyncSession
    ):
        """존재하지 않는 코드 삭제 시 예외"""
        service = InviteCodeService(db_session)
        with pytest.raises(CodeNotFoundError):
            await service.delete_code(99999)


class TestGetStats:
    """통계 테스트"""

    @pytest.mark.asyncio
    async def test_get_stats(
        self,
        db_session: AsyncSession,
        admin_user: User,
        normal_user: User,
    ):
        """유형별 통계"""
        service = InviteCodeService(db_session)
        codes1 = await service.generate_codes(
            user_type="1학년", count=5, admin_id=admin_user.id
        )
        codes2 = await service.generate_codes(
            user_type="2학년", count=3, admin_id=admin_user.id
        )
        await db_session.commit()

        # 1학년 2개 사용
        await service.use_code(codes1[0].code, normal_user.id)
        await service.use_code(codes1[1].code, normal_user.id)
        # 2학년 1개 사용
        await service.use_code(codes2[0].code, normal_user.id)
        await db_session.commit()

        stats = await service.get_stats()
        assert len(stats) == 2

        stat1 = next(
            s for s in stats if s["user_type"] == "1학년"
        )
        assert stat1["total"] == 5
        assert stat1["used"] == 2
        assert stat1["unused"] == 3

        stat2 = next(
            s for s in stats if s["user_type"] == "2학년"
        )
        assert stat2["total"] == 3
        assert stat2["used"] == 1
        assert stat2["unused"] == 2
