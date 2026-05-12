"""
실행 시점 스키마 보정 모듈 패키지
"""

from .criteria_schema import (
    ensure_criteria_file_path_column,
    ensure_criteria_display_alias_column,
)
from .drop_invite_codes_table import drop_invite_codes_table
from .user_profiles import ensure_user_profiles_table
from .users_lockout_columns import ensure_users_lockout_columns
from .chat_sessions_user_type_rename import (
    rename_chat_session_in_service_teacher_label,
)

__all__ = [
    "drop_invite_codes_table",
    "ensure_criteria_file_path_column",
    "ensure_criteria_display_alias_column",
    "ensure_user_profiles_table",
    "ensure_users_lockout_columns",
    "rename_chat_session_in_service_teacher_label",
]
