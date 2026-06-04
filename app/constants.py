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
    "기타",
]

PRESERVICE_UNIVERSITY_REGIONS = [
    "서울교대",
    "경인교대",
    "공주교대",
    "광주교대",
    "대구교대",
    "부산교대",
    "전주교대",
    "진주교대",
    "청주교대",
    "춘천교대",
    "한국교원대",
    "기타",
]

USER_AUTH_ROLES = [
    "teacher",
    "preservice_teacher",
]
