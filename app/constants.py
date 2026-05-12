"""프로젝트 공용 상수"""

SESSION_USER_TYPE_LABELS = [
    "1학년",
    "2학년",
    "3학년",
    "4학년",
    "교사",
]

# Backward-compatible alias for existing admin analytics code.
# These values are session-segmentation labels, not active invite-code auth.
USER_TYPES = SESSION_USER_TYPE_LABELS

TEACHER_REGIONS = [
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "세종",
    "경기",
    "충북",
    "충남",
    "전북",
    "전남",
    "경북",
    "경남",
    "강원",
    "제주",
]

PRESERVICE_UNIVERSITY_REGIONS = [
    "서울",
    "경인",
    "공주",
    "광주",
    "대구",
    "부산",
    "전주",
    "진주",
    "청주",
    "춘천",
    "한국교원대",
]

USER_AUTH_ROLES = [
    "teacher",
    "preservice_teacher",
]
