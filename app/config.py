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

    # 데이터베이스
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./data/app.db",
        description="데이터베이스 URL",
    )

    # Google Gemini API
    GOOGLE_API_KEY: str = Field(..., description="Google API 키")
    GEMINI_QNA_MODEL: str = Field(
        default="gemini-2.0-flash-exp", description="QnA용 모델"
    )
    GEMINI_EVAL_MODEL: str = Field(
        default="gemini-2.0-flash-thinking-exp",
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


# 전역 설정 인스턴스
settings = Settings()
