"""프로젝트 공용 상수"""

UNPROFILED_USER_TYPE = "미지정"

SESSION_USER_TYPE_LABELS = [
    "1학년",
    "2학년",
    "3학년",
    "4학년",
    "교사",
    UNPROFILED_USER_TYPE,
]

# Backward-compatible alias for existing admin analytics code.
# These values are session-segmentation labels, not active invite-code auth.
USER_TYPES = SESSION_USER_TYPE_LABELS
