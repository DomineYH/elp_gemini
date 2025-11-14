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

        사용자 식별 로직:
        - username이 존재하면 해당 사용자로 로그인 (nickname은 업데이트)
        - username이 없으면 새로운 사용자 생성 후 로그인

        Args:
            username: 사용자 ID (고유 식별자)
            nickname: 닉네임 (변경 가능)

        Returns:
            인증된 User 객체 (기존 또는 새로 생성)
        """
        # 1. username으로 사용자 검색
        existing_user = await self.get_user_by_username(username)

        # 2. username이 존재하는 경우 → 기존 사용자로 로그인
        if existing_user:
            # nickname이 다르면 업데이트
            if existing_user.nickname != nickname:
                existing_user.nickname = nickname
                await self.db.commit()
            return existing_user

        # 3. username이 없는 경우 → 새로운 사용자 생성
        from app.schemas.users import UserCreate

        user_data = UserCreate(
            username=username,
            nickname=nickname,
            email=None,  # 이메일은 선택 사항
            password=None,  # 비밀번호는 선택 사항 (간단한 로그인)
            is_admin=False,  # 기본적으로 일반 사용자
        )

        new_user = await self.create_user(user_data)
        await self.db.commit()

        return new_user

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
