"""
실행 시점 스키마 보정 모듈 패키지
"""

from .chat_sessions_user_type_rename import (
    rename_chat_session_in_service_teacher_label,
)
from .criteria_schema import (
    ensure_app_state_table,
    ensure_criteria_display_alias_column,
    ensure_criteria_file_path_column,
)
from .criteria_stable_id import ensure_criteria_stable_id_column
from .drop_invite_codes_table import drop_invite_codes_table
from .drop_user_profiles import drop_user_profiles
from .drop_users_email_column import drop_users_email_column
from .lessonplan_uploads_table import ensure_lessonplan_uploads_table
from .preservice_region_kyodae_rename import (
    rename_preservice_university_regions,
)
from .users_lockout_columns import ensure_users_lockout_columns
from .users_survey_completed_column import (
    ensure_users_survey_completed_column,
)

__all__ = [
    "drop_invite_codes_table",
    "drop_user_profiles",
    "drop_users_email_column",
    "ensure_app_state_table",
    "ensure_criteria_file_path_column",
    "ensure_criteria_display_alias_column",
    "ensure_criteria_stable_id_column",
    "ensure_users_lockout_columns",
    "ensure_users_survey_completed_column",
    "ensure_lessonplan_uploads_table",
    "rename_chat_session_in_service_teacher_label",
    "rename_preservice_university_regions",
]
