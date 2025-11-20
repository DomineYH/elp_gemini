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
    user_id: int,
    action: str,
    details: Dict[str, Any] = None,
    success: bool = True,
    logger_name: str = "app.audit",
) -> None:
    """
    사용자 액션 감사 로깅

    Args:
        user_id: 사용자 ID
        action: 액션 타입
        details: 추가 정보 (딕셔너리)
        success: 성공 여부
        logger_name: 로거 이름 (기본: app.audit)
    """
    logger = logging.getLogger(logger_name)
    status = "SUCCESS" if success else "FAILURE"

    log_data = {
        "user_id": user_id,
        "action": action,
        "status": status,
    }

    if details:
        log_data["details"] = details

    log_msg = f"[AUDIT] {log_data}"

    if success:
        logger.info(log_msg)
    else:
        logger.warning(log_msg)


def log_auth_event(
    event_type: str,
    user_id: int = None,
    username: str = None,
    success: bool = True,
    reason: str = None,
) -> None:
    """
    인증 이벤트 감사 로깅

    Args:
        event_type: 이벤트 타입 (login, logout,
            permission_denied)
        user_id: 사용자 ID
        username: 사용자명
        success: 성공 여부
        reason: 실패 이유
    """
    logger = logging.getLogger("app.auth")
    status = "SUCCESS" if success else "FAILURE"

    log_data = {
        "event": event_type,
        "status": status,
        "user_id": user_id,
        "username": username,
    }

    if not success and reason:
        log_data["reason"] = reason

    log_msg = f"[AUTH] {log_data}"

    if success:
        logger.info(log_msg)
    else:
        logger.warning(log_msg)
