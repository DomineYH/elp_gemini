"""
로깅 구성
구조화된 로깅 설정 및 로거 생성
"""
import logging
import sys
from typing import Any, Dict


def setup_logging(debug: bool = False) -> None:
    """
    애플리케이션 로깅 설정

    Args:
        debug: 디버그 모드 활성화 여부
    """
    log_level = logging.DEBUG if debug else logging.INFO

    # 루트 로거 설정
    logging.basicConfig(
        level=log_level,
        format=(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # 외부 라이브러리 로그 레벨 조정
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.WARNING
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    로거 인스턴스 가져오기

    Args:
        name: 로거 이름 (보통 __name__ 사용)

    Returns:
        Logger 인스턴스
    """
    return logging.getLogger(name)


def log_api_call(
    logger: logging.Logger,
    model: str,
    operation: str,
    latency_ms: int = None,
    extra: Dict[str, Any] = None,
) -> None:
    """
    LLM API 호출 로깅

    Args:
        logger: 로거 인스턴스
        model: 사용된 모델 이름
        operation: 작업 타입 (qna, evaluation 등)
        latency_ms: 응답 시간 (밀리초)
        extra: 추가 정보
    """
    log_data = {
        "model": model,
        "operation": operation,
        "latency_ms": latency_ms,
    }

    if extra:
        log_data.update(extra)

    logger.info(f"LLM API 호출: {log_data}")


def log_user_action(
    logger: logging.Logger,
    user_id: int,
    action: str,
    resource: str = None,
    success: bool = True,
) -> None:
    """
    사용자 액션 로깅

    Args:
        logger: 로거 인스턴스
        user_id: 사용자 ID
        action: 액션 타입
        resource: 대상 리소스
        success: 성공 여부
    """
    status = "성공" if success else "실패"
    log_msg = (
        f"사용자 액션 - "
        f"user_id={user_id}, "
        f"action={action}, "
        f"resource={resource}, "
        f"status={status}"
    )

    if success:
        logger.info(log_msg)
    else:
        logger.warning(log_msg)
