"""
인증 서비스
사용자 인증 및 비밀번호 관리
"""
from typing import Optional
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.users import User
from app.schemas.users import UserCreate

# 비밀번호 해싱 컨텍스트 (T020)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """인증 서비스 클래스"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def authenticate_user(
        self, username: str, nickname: str
    ) -> Optional[User]:
        """
        사용자 인증 또는 생성

        사용자 식별 로직 (수정됨):
        - username만으로 사용자 식별
        - 기존 사용자가 있으면 nickname 업데이트
        - 새로운 사용자면 username과 nickname으로 생성
        - DB username 필드는 원본 username을 그대로 저장

        Args:
            username: 사용자 ID (원본)
            nickname: 닉네임

        Returns:
            인증된 User 객체 (기존 또는 새로 생성)
        """
        # 1. username으로 사용자 검색
        existing_user = await self.get_user_by_username(username)

        # 2. 기존 사용자가 있는 경우
        if existing_user:
            # nickname이 변경되었으면 업데이트
            if existing_user.nickname != nickname:
                existing_user.nickname = nickname
                await self.db.commit()
                await self.db.refresh(existing_user)
            return existing_user

        # 3. 새로운 사용자 생성
        from app.schemas.users import UserCreate

        user_data = UserCreate(
            username=username,  # 원본 username 저장
            nickname=nickname,
            email=None,  # 이메일은 선택 사항
            password=None,  # 비밀번호는 선택 사항 (간단한 로그인)
            is_admin=False,  # 기본적으로 일반 사용자
        )

        new_user = await self.create_user(user_data)
        await self.db.commit()

        return new_user

    async def authenticate_admin(
        self, admin_id: str, password: str
    ) -> Optional[User]:
        """
        관리자 인증 (ID + 비밀번호)

        관리자 ID와 비밀번호를 검증하여 관리자 사용자를 반환합니다.

        Args:
            admin_id: 관리자 ID
            password: 비밀번호

        Returns:
            인증된 관리자 User 객체 또는 None
        """
        # 1. admin_id로 사용자 검색
        user = await self.get_user_by_username(admin_id)

        # 2. 사용자가 없거나 관리자가 아닌 경우
        if not user or not user.is_admin:
            return None

        # 3. 비밀번호 검증
        if not user.hashed_password:
            return None

        if not self.verify_password(password, user.hashed_password):
            return None

        return user

    async def get_user_by_username_and_nickname(
        self, username: str, nickname: str
    ) -> Optional[User]:
        """
        [DEPRECATED] 이 메서드는 더 이상 사용되지 않습니다.
        username만으로 사용자를 식별하도록 변경되었습니다.
        대신 get_user_by_username()을 사용하세요.

        Args:
            username: 사용자 ID (원본)
            nickname: 닉네임

        Returns:
            User 객체 또는 None
        """
        # 하위 호환성을 위해 username으로만 조회
        return await self.get_user_by_username(username)

    async def get_user_by_username(
        self, username: str
    ) -> Optional[User]:
        """
        사용자 ID로 사용자 조회

        Args:
            username: 사용자 ID

        Returns:
            User 객체 또는 None
        """
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_user_by_email(
        self, email: str
    ) -> Optional[User]:
        """
        이메일로 사용자 조회

        Args:
            email: 이메일 주소

        Returns:
            User 객체 또는 None
        """
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """
        ID로 사용자 조회

        Args:
            user_id: 사용자 ID

        Returns:
            User 객체 또는 None
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def create_user(self, user_data: UserCreate) -> User:
        """
        새 사용자 생성

        Args:
            user_data: 사용자 생성 데이터

        Returns:
            생성된 User 객체
        """
        hashed_password = None
        if user_data.password:
            hashed_password = self.hash_password(user_data.password)

        user = User(
            username=user_data.username,
            nickname=user_data.nickname,
            email=user_data.email,
            hashed_password=hashed_password,
            is_admin=user_data.is_admin,
        )

        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)

        return user

    @staticmethod
    def hash_password(password: str) -> str:
        """
        비밀번호 해싱

        Args:
            password: 평문 비밀번호

        Returns:
            해싱된 비밀번호
        """
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(
        plain_password: str, hashed_password: str
    ) -> bool:
        """
        비밀번호 검증

        Args:
            plain_password: 평문 비밀번호
            hashed_password: 해싱된 비밀번호

        Returns:
            검증 결과 (True/False)
        """
        return pwd_context.verify(plain_password, hashed_password)

    async def authenticate_user_with_code(
        self, user_type: str, code: str
    ) -> User:
        """
        초대 코드 기반 사용자 인증

        Args:
            user_type: 사용자 유형 (1학년 등)
            code: 초대 코드

        Returns:
            인증된 User 객체

        Raises:
            ValueError: 유효하지 않은 코드
        """
        from app.services.invite_code_service import (
            InviteCodeService,
        )

        invite_service = InviteCodeService(self.db)
        invite = await invite_service.validate_code(
            code, user_type
        )
        if not invite:
            raise ValueError(
                "유효하지 않은 초대 코드입니다."
            )

        # 이미 사용된 코드 → 기존 사용자 반환
        if invite.user_id:
            user = await self.get_user_by_id(
                invite.user_id
            )
            if user:
                return user

        # 새 사용자 생성 (username=코드, nickname=유형)
        user_data = UserCreate(
            username=code.upper(),
            nickname=user_type,
        )
        new_user = await self.create_user(user_data)
        await invite_service.use_code(
            code, new_user.id
        )
        await self.db.commit()
        return new_user
