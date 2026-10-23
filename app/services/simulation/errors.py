"""
시뮬레이션 오류 코드 → HTTP 상태·한국어 메시지 (PLAN 2.5, 표는 여기 하나)
"""

from fastapi import HTTPException

# 코드: (상태, 메시지). 후속 티켓은 자기 코드 행만 추가한다.
CODES = {
    "SESSION_NOT_FOUND": (404, "시뮬레이션 세션을 찾을 수 없습니다."),
    "NO_FEEDBACK": (404, "아직 생성된 시뮬레이션 피드백이 없습니다."),
    "NO_UPLOAD": (404, "먼저 지도안을 업로드해 주세요."),
    "LIBRARY_NOT_FOUND": (404, "내 페르소나를 찾을 수 없습니다."),
    "PHASE_NOT_CURRENT": (409, "현재 국면이 아닙니다."),
    "SESSION_FINISHED": (409, "이미 끝난 시뮬레이션입니다."),
    "PHASE_NOT_ENTERED": (409, "아직 현재 국면에 들어가지 않았습니다."),
    "NOT_ALL_AGREED": (
        409,
        "아직 모든 학생이 다음 국면에 동의하지 않았습니다.",
    ),
    "TURN_LIMIT": (
        409,
        "상한에 도달했습니다. 수업을 종료하고 피드백을 받으세요.",
    ),
    "NOTHING_TO_REGENERATE": (409, "다시 생성할 학생 반응이 없습니다."),
    "CONFLICT_RETRY": (
        409,
        "동시에 요청이 처리되었습니다. 다시 시도해 주세요.",
    ),
    "SESSION_NOT_FINISHED": (
        409,
        "수업을 종료한 뒤에 피드백을 받을 수 있습니다.",
    ),
    "NO_SAMPLE_SESSION": (
        409,
        "미리보기에 쓸 종료된 시뮬레이션이 없습니다. "
        "먼저 한 번 끝까지 진행해 주세요.",
    ),
    "TOO_MANY_PERSONAS": (
        422,
        "학생 수가 관리자가 정한 최대 인원을 넘었습니다.",
    ),
    "UNKNOWN_PERSONA": (422, "알 수 없는 페르소나입니다."),
    "DUPLICATE_PSEUDONYM": (
        422,
        "가명이 중복되었거나 사용할 수 없는 이름입니다.",
    ),
    "INVALID_PERSONA": (400, "페르소나 입력값을 확인해 주세요."),
    "RESOURCE_EXHAUSTED": (
        429,
        "AI 사용량이 잠시 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.",
    ),
    "MODEL_OVERLOADED": (
        503,
        "AI 모델이 혼잡합니다. 잠시 후 다시 시도해 주세요.",
    ),
    "ADAPT_FAILED": (
        502,
        "페르소나 번안 결과를 읽지 못했습니다. 다시 시도해 주세요.",
    ),
    "FEEDBACK_PARSE_FAILED": (
        502,
        "피드백 결과를 읽지 못했습니다. 다시 시도해 주세요.",
    ),
}
RETRY_AFTER_SECONDS = "30"


class SimulationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

    def to_http(self) -> HTTPException:
        status, message = CODES[self.code]
        headers = (
            {"Retry-After": RETRY_AFTER_SECONDS}
            if status in (429, 503)
            else None
        )
        return HTTPException(
            status_code=status,
            detail={"code": self.code, "message": message},
            headers=headers,
        )
