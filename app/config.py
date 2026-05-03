"""
애플리케이션 구성 관리
Pydantic Settings를 사용한 환경 변수 관리
"""
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """애플리케이션 설정"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # 애플리케이션
    DEBUG: bool = Field(default=False, description="디버그 모드")
    SECRET_KEY: str = Field(
        ..., min_length=32, description="세션 암호화 키"
    )
    ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000"],
        description="CORS 허용 오리진",
    )

    # 세션 쿠키 설정
    SESSION_COOKIE_NAME: str = Field(
        default="session", description="세션 쿠키 이름"
    )
    SESSION_MAX_AGE: int = Field(
        default=60 * 60 * 24 * 7,
        description="세션 최대 유효 시간(초, 기본 7일)",
    )
    SESSION_SAME_SITE: str = Field(
        default="lax", description="SameSite 쿠키 속성"
    )
    SESSION_HTTPS_ONLY: bool = Field(
        default=True,
        description="HTTPS에서만 세션 쿠키 전송",
    )
    SESSION_HTTP_ONLY: bool = Field(
        default=True, description="JavaScript 접근 차단"
    )

    # 데이터베이스
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./data/app.db",
        description="데이터베이스 URL",
    )

    # Google Gemini API
    GOOGLE_API_KEY: str = Field(..., description="Google API 키")
    GEMINI_QNA_MODEL: str = Field(
        default="gemini-3-flash-preview", description="QnA용 모델"
    )
    GEMINI_EVAL_MODEL: str = Field(
        default="gemini-3-flash-preview",
        description="평가용 모델",
    )

    # File Search
    FS_MAIN_STORE_NAME: str = Field(
        default="main-store", description="메인 파일 검색 스토어"
    )
    FS_RUBRIC_STORE_NAME: str = Field(
        default="rubric-store", description="루브릭 파일 검색 스토어"
    )

    # File Search 설정 (청킹)
    FS_CHUNKING_MAX_TOKENS: int = Field(
        default=512, description="청킹 최대 토큰 수 (Google API 최대값: 512)"
    )
    FS_CHUNKING_OVERLAP_TOKENS: int = Field(
        default=100, description="청킹 중복 토큰 수"
    )

    # File Search 설정 (업로드)
    FS_UPLOAD_TIMEOUT: int = Field(
        default=300, description="파일 업로드 타임아웃 (초)"
    )
    FS_POLL_INTERVAL: int = Field(
        default=5, description="업로드 상태 확인 간격 (초)"
    )

    # QnA 설정
    QNA_TEMPERATURE: float = Field(
        default=0.7, description="QnA 생성 온도 (0.0-1.0)"
    )
    QNA_ENABLE_CITATIONS: bool = Field(
        default=True, description="Citation 정보 활성화"
    )

    # 파일 업로드
    MAX_UPLOAD_SIZE: int = Field(
        default=52428800, description="최대 업로드 크기 (50MB)"
    )
    UPLOAD_DIR: str = Field(
        default="./data/uploads", description="업로드 디렉토리"
    )

    # Google Cloud Configuration
    GOOGLE_APPLICATION_CREDENTIALS: str = Field(
        default="./credentials/google-cloud-key.json",
        description="Google Cloud 서비스 계정 키 파일 경로",
    )
    GOOGLE_PROJECT_ID: str = Field(
        default="", description="Google Cloud 프로젝트 ID"
    )

    # Vector DB Paths (Criteria vs User separation)
    CRITERIA_VECTOR_DB_PATH: str = Field(
        default="./data/vector_db/criteria/",
        description="평가 기준 전용 벡터 DB 경로",
    )
    USER_VECTOR_DB_PATH: str = Field(
        default="./data/vector_db/user/",
        description="사용자 문서 전용 벡터 DB 경로",
    )

    # Criteria Upload
    CRITERIA_UPLOAD_DIR: str = Field(
        default="./data/uploads/criteria/",
        description="평가 기준 파일 업로드 디렉토리",
    )

    # 관리자 로그인 brute-force 방어 (Issue #5)
    RATE_LIMIT_ENABLED: bool = Field(
        default=True,
        description="rate limit 활성화 (테스트 환경에서 false)",
    )
    ADMIN_LOGIN_RATE_LIMIT: str = Field(
        default="5/minute",
        description="/auth/login/admin 의 IP 기반 rate limit",
    )
    USER_LOGIN_RATE_LIMIT: str = Field(
        default="30/minute",
        description="/auth/login/user 의 IP 기반 rate limit",
    )
    ADMIN_MAX_FAILED_ATTEMPTS: int = Field(
        default=10,
        ge=1,
        le=100,
        description="관리자 로그인 잠금 임계치 (실패 횟수)",
    )
    ADMIN_LOCKOUT_DURATION_MINUTES: int = Field(
        default=5,
        ge=1,
        le=1440,
        description="관리자 로그인 잠금 지속 시간 (분)",
    )


# 전역 설정 인스턴스
settings = Settings()
