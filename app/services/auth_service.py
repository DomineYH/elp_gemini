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
        - username과 nickname이 모두 일치하는 사용자가 있으면 해당 사용자로 로그인
        - 둘 중 하나라도 다르면 새로운 사용자로 간주하여 생성 후 로그인
        - DB username 필드는 username_nickname 형식으로 고유하게 저장

        Args:
            username: 사용자 ID (원본)
            nickname: 닉네임

        Returns:
            인증된 User 객체 (기존 또는 새로 생성)
        """
        # 1. username과 nickname으로 사용자 검색
        existing_user = await self.get_user_by_username_and_nickname(username, nickname)

        # 2. username과 nickname이 모두 일치하는 경우 → 기존 사용자로 로그인
        if existing_user:
            return existing_user

        # 3. 일치하는 사용자가 없는 경우 → 새로운 사용자 생성
        # DB의 username 필드에는 고유한 값(username_nickname)을 저장
        import secrets

        # 고유한 DB username 생성: username_nickname 형식
        db_username = f"{username}_{nickname}"

        # 만약 동일한 조합이 이미 있다면 (nickname에 언더스코어 포함 케이스) 고유 suffix 추가
        db_username_exists = await self.get_user_by_username(db_username)
        if db_username_exists:
            unique_suffix = secrets.token_hex(4)
            db_username = f"{username}_{nickname}_{unique_suffix}"

        # 새 사용자 생성
        from app.schemas.users import UserCreate

        user_data = UserCreate(
            username=db_username,  # DB에는 고유한 username 저장
            nickname=nickname,
            email=None,  # 이메일은 선택 사항
            password=None,  # 비밀번호는 선택 사항 (간단한 로그인)
            is_admin=False,  # 기본적으로 일반 사용자
        )

        new_user = await self.create_user(user_data)
        await self.db.commit()

        return new_user

    async def get_user_by_username_and_nickname(
        self, username: str, nickname: str
    ) -> Optional[User]:
        """
        사용자 ID와 닉네임으로 사용자 조회
        DB의 username 필드는 username_nickname 형식으로 저장됨

        Args:
            username: 사용자 ID (원본)
            nickname: 닉네임

        Returns:
            User 객체 또는 None
        """
        # DB에서는 username_nickname 형식으로 저장되므로
        db_username = f"{username}_{nickname}"
        result = await self.db.execute(
            select(User).where(
                User.username == db_username,
                User.nickname == nickname
            )
        )
        return result.scalar_one_or_none()

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
