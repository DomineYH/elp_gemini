"""
인증 서비스
사용자 인증 및 비밀번호 관리
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from passlib.context import CryptContext
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.users import User
from app.schemas.users import (
    UserCreate,
    normalize_email_address,
    normalize_user_id,
    validate_password_strength,
    validate_user_id,
)
from app.utils.logging import log_auth_event

# 비밀번호 해싱 컨텍스트 (T020)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

logger = logging.getLogger(__name__)

# 타이밍 사이드채널 차단용 사전계산 더미 bcrypt 해시 (issue #6).
# 런타임/import 시 hash()를 새로 계산하지 않아 cold-start 타이밍 스파이크와
# 동시성 race를 피한다. 평문은 검증되지 않으며 verify 비용만 사용한다.
_DUMMY_BCRYPT_HASH: str = (
    "$2b$12$Fif9YgEbtiOSRyzBnaWFTeS1g06F.zPP2MARUT911dzcU0lL9jooy"
)


@dataclass
class AdminLoginResult:
    """관리자 로그인 결과 컨테이너

    Fields:
        user: 인증 성공 시 User 객체, 그 외 None
        locked: 계정이 brute-force lockout 상태이면 True
        retry_at: lockout이 풀리는 시각 (locked=True일 때만 의미 있음)
    """

    user: Optional[User] = None
    locked: bool = False
    retry_at: Optional[datetime] = None


class AuthService:
    """인증 서비스 클래스"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _dummy_password_verify(password: str) -> None:
        """타이밍 일치를 위해 더미 bcrypt 검증을 실행한다.
        결과값은 항상 무시한다 (issue #6).
        실패 시에도 외부로 예외를 누출시키지 않되, 내부적으로 경고 로깅하여
        타이밍 보정이 무력화된 사실을 운영팀이 감지할 수 있게 한다."""
        try:
            pwd_context.verify(password, _DUMMY_BCRYPT_HASH)
        except Exception as e:
            logger.warning(
                "dummy_password_verify failed (timing equalizer degraded): %s",
                type(e).__name__,
            )

    async def _touch_locked_attempt(self, user: User) -> None:
        """잠금 상태 실패를 invalid-password 실패와 같은 DB 비용으로 기록한다.

        잠금 중 추가 시도는 잠금 카운터/해제 시각을 바꾸면 안 되지만,
        issue #6 방어상 invalid-password 경로의 atomic UPDATE + refresh 비용과
        같은 모양의 작업을 수행해야 locked 여부가 timing oracle 이 되지 않는다.
        """
        now = datetime.utcnow()
        stmt = (
            update(User)
            .where(User.id == user.id)
            .values(
                failed_login_count=User.failed_login_count,
                last_failed_login_at=now,
                locked_until=User.locked_until,
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()
        await self.db.refresh(user)

    async def _touch_missing_admin_attempt(self) -> None:
        """존재하지 않거나 관리자가 아닌 admin_id 실패 경로의 DB 비용 보정.

        실제 관리자 invalid-password 경로는 실패 카운터 UPDATE + COMMIT 이
        발생한다. missing/non-admin 경로가 bcrypt 보정 후 즉시 반환하면
        여전히 DB 쓰기 유무로 admin_id 열거가 가능할 수 있으므로, 어떤
        사용자 행도 변경하지 않는 no-op UPDATE + COMMIT 으로 왕복 비용을
        맞춘다.
        """
        now = datetime.utcnow()
        stmt = (
            update(User)
            .where(User.id == -1)
            .values(last_failed_login_at=now)
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def authenticate_admin(
        self, admin_id: str, password: str
    ) -> AdminLoginResult:
        """
        관리자 인증 (ID + 비밀번호) — brute-force 방어 포함

        - 잠긴 계정은 비밀번호 검증을 건너뛴다 (timing leak 차단)
        - 공개/익명 로그인 실패는 hard lockout 직전에서 soft-cap 한다
        - 성공 시 카운터를 리셋한다
        - 이 서비스는 bcrypt/DB 작업 비용을 보정한다. 외부 응답의
          wall-clock floor 는 HTTP 경계(`login_admin`) 또는 동등한
          호출자가 적용해야 한다.

        Returns:
            AdminLoginResult: user(성공 시), locked, retry_at
        """
        # 1. admin_id로 사용자 검색
        user = await self.get_user_by_username(admin_id)

        # 2. 사용자가 없거나 관리자가 아닌 경우 — 동일 응답
        if not user or not user.is_admin:
            self._dummy_password_verify(password)
            await self._touch_missing_admin_attempt()
            return AdminLoginResult(user=None, locked=False)

        # 3. 잠금 상태면 비밀번호 검증 없이 즉시 반환
        if self._is_account_locked(user):
            self._dummy_password_verify(password)
            # invalid-password 경로의 DB UPDATE 비용과 타이밍을 맞춘다.
            await self._touch_locked_attempt(user)
            log_auth_event(
                "lockout_attempt_blocked",
                user_id=user.id,
                username=admin_id,
                success=False,
                reason=f"locked_until={user.locked_until.isoformat()}",
            )
            return AdminLoginResult(
                user=None,
                locked=True,
                retry_at=user.locked_until,
            )

        # 4. 비밀번호 미설정 → 인증 실패로 카운터 증가
        if not user.hashed_password:
            self._dummy_password_verify(password)
            await self._record_failed_admin_login(user, admin_id)
            return AdminLoginResult(user=None, locked=False)

        # 5. 비밀번호 검증
        if not self.verify_password(password, user.hashed_password):
            await self._record_failed_admin_login(user, admin_id)
            return AdminLoginResult(user=None, locked=False)

        # 6. 성공 → 카운터 리셋
        await self._reset_admin_login_counter(user)
        return AdminLoginResult(user=user, locked=False)

    def _is_account_locked(self, user: User) -> bool:
        """잠금 시각이 미래라면 잠금 상태."""
        if user.locked_until is None:
            return False
        return user.locked_until > datetime.utcnow()

    async def _record_failed_admin_login(
        self, user: User, admin_id: str
    ) -> None:
        """실패 카운터 +1, hard lockout 직전에서 soft-cap.

        동시 실패 요청 사이의 lost-update 회피를 위해 단일 atomic
        UPDATE로 카운터 증가를 적용한다.

        Issue #13: 이 경로는 인증되지 않은 public admin-login endpoint 에서
        호출되므로, 잘못된 비밀번호만으로 `locked_until` 을 설정하면
        익명 공격자가 brute-force 방어를 관리자 계정 DoS 로 무기화할 수
        있다. 기존 수동/운영 lockout 은 계속 존중하되, 공개 실패 누적은
        hard lockout 임계치보다 하나 작은 값에서 멈춘다. 실제 시도량 제한은
        IP/admin_id rate limit 과 실패 응답 시간 보정이 담당한다.
        """
        max_attempts = int(settings.ADMIN_MAX_FAILED_ATTEMPTS)
        soft_failure_cap = max(max_attempts - 1, 0)
        now = datetime.utcnow()

        # Lockout 만료 여부: locked_until 이 NULL 이 아니고 과거인 경우
        lockout_expired = User.locked_until.is_not(None) & (
            User.locked_until <= now
        )
        if soft_failure_cap == 0:
            next_failed_count = 0
        else:
            next_failed_count = case(
                (lockout_expired, 1),
                (
                    User.failed_login_count < soft_failure_cap,
                    User.failed_login_count + 1,
                ),
                else_=User.failed_login_count,
            )

        stmt = (
            update(User)
            .where(User.id == user.id)
            .values(
                failed_login_count=next_failed_count,
                last_failed_login_at=now,
                locked_until=case(
                    # 만료된 lockout 은 정리하되, 공개 실패로 새 lockout 을
                    # 만들지는 않는다 (Issue #13).
                    (lockout_expired, None),
                    else_=User.locked_until,
                ),
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()
        await self.db.refresh(user)

        current = user.failed_login_count

        log_auth_event(
            "login",
            user_id=user.id,
            username=admin_id,
            success=False,
            reason=f"failed_attempt={current}/{max_attempts}",
        )

        if soft_failure_cap > 0 and current >= soft_failure_cap:
            log_auth_event(
                "admin_login_soft_capped",
                user_id=user.id,
                username=admin_id,
                success=False,
                reason=(
                    f"failed_attempt_cap={current}/{soft_failure_cap}; "
                    "hard_lockout_not_set_for_public_endpoint"
                ),
            )

    async def _reset_admin_login_counter(self, user: User) -> None:
        """성공 시 카운터/잠금 정보 리셋 (atomic UPDATE)."""
        if (
            not user.failed_login_count
            and user.locked_until is None
            and user.last_failed_login_at is None
        ):
            return

        stmt = (
            update(User)
            .where(User.id == user.id)
            .values(
                failed_login_count=0,
                locked_until=None,
                last_failed_login_at=None,
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()
        await self.db.refresh(user)

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

    @staticmethod
    def normalize_email(email: str) -> str:
        """이메일 저장/조회용 정규화."""
        return normalize_email_address(email)

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
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return None

        result = await self.db.execute(
            select(User).where(User.email == normalized_email)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _has_valid_custom_id(user: User) -> bool:
        try:
            validate_user_id(user.username)
        except ValueError:
            return False
        return True

    @staticmethod
    def _is_login_capable(user: User) -> bool:
        return user.email is not None or AuthService._has_valid_custom_id(user)

    async def get_regular_legacy_email_user(
        self, email: str
    ) -> Optional[User]:
        """이메일만 로그인 식별자로 가진 레거시 일반 사용자를 조회한다."""
        user = await self.get_user_by_email(email)
        if not user or user.is_admin:
            return None
        if self._has_valid_custom_id(user):
            return None
        return user

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

    async def get_regular_user_by_username(
        self, user_id: str
    ) -> Optional[User]:
        """사용자 지정 id(=username)로 일반 사용자를 조회한다.

        관리자 계정은 일반 사용자 로그인 흐름에서 제외한다.
        """
        normalized = normalize_user_id(user_id)
        if not normalized:
            return None

        result = await self.db.execute(
            select(User).where(
                func.lower(User.username) == normalized,
                User.is_admin.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def register_regular_user(
        self, user_id: str, password: str
    ) -> User:
        """일반 사용자 등록 (Issue #90, id+비밀번호).

        - id 는 영문/숫자 9자 이하, 대소문자 무시 고유, 예약어 금지
        - username/nickname 모두 정규화된 id 로 저장하며 email 은 사용하지 않음
        """
        normalized_id = validate_user_id(user_id)

        # 관리자 계정을 포함한 전체 username 네임스페이스에서 중복 확인
        result = await self.db.execute(
            select(User).where(func.lower(User.username) == normalized_id)
        )
        if result.scalar_one_or_none():
            raise ValueError("이미 사용 중인 아이디입니다.")

        user_data = UserCreate(
            username=normalized_id,
            nickname=normalized_id,
            email=None,
            password=password,
            is_admin=False,
        )
        try:
            user = await self.create_user(user_data)
            await self.db.commit()
            await self.db.refresh(user)
            return user
        except IntegrityError as exc:
            # 사전 확인을 통과한 동시 등록(레이스/더블 제출)도 친절한 409로 처리
            await self.db.rollback()
            raise ValueError("이미 사용 중인 아이디입니다.") from exc
        except Exception:
            await self.db.rollback()
            raise

    async def authenticate_regular_user_by_username(
        self, user_id: str, password: str
    ) -> Optional[User]:
        """일반 사용자 id+비밀번호 인증."""
        user = await self.get_regular_user_by_username(user_id)
        if not user or not user.hashed_password:
            # 미존재 id 도 dummy verify 로 bcrypt 비용 보정 (타이밍 완화)
            self._dummy_password_verify(password)
            return None

        if not self.verify_password(password, user.hashed_password):
            return None

        return user

    async def authenticate_regular_user_by_legacy_email(
        self, email: str, password: str
    ) -> Optional[User]:
        """레거시 이메일 식별자 일반 사용자 인증."""
        user = await self.get_regular_legacy_email_user(email)
        if not user or not user.hashed_password:
            self._dummy_password_verify(password)
            return None

        if not self.verify_password(password, user.hashed_password):
            return None

        return user

    async def admin_set_user_password(
        self, user_id: int, new_password: str
    ) -> User:
        """
        관리자 전용 일반 사용자 비밀번호 변경 서비스.

        실제 관리자 권한 확인은 라우터 의존성에서 수행하고, 이
        서비스는 대상이 일반 사용자임을 보장한다.
        """
        validated_password = validate_password_strength(new_password)
        user = await self.get_user_by_id(user_id)

        if not user:
            raise ValueError("사용자를 찾을 수 없습니다.")
        if user.is_admin:
            raise ValueError(
                "관리자 계정 비밀번호는 이 기능으로 변경할 수 없습니다."
            )
        if not self._is_login_capable(user):
            raise ValueError(
                "로그인 가능한 식별자가 없는 사용자는 "
                "비밀번호를 변경할 수 없습니다."
            )

        user.hashed_password = self.hash_password(validated_password)
        user.failed_login_count = 0
        user.locked_until = None
        user.last_failed_login_at = None

        await self.db.commit()
        await self.db.refresh(user)
        log_auth_event(
            "password_change",
            user_id=user.id,
            username=user.username,
            success=True,
        )
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
