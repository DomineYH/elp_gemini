"""업로드 한도가 settings.MAX_UPLOAD_SIZE 단일 출처에서 파생되는지 검증."""
from app.config import settings
from app.services.file_validator import FileValidator


def test_settings_max_upload_size_is_50mb():
    assert settings.MAX_UPLOAD_SIZE == 50 * 1024 * 1024


def test_file_validator_defaults_to_settings_max_upload_size():
    validator = FileValidator()
    assert validator.max_file_size == settings.MAX_UPLOAD_SIZE


def test_file_validator_explicit_override_still_works():
    validator = FileValidator(max_size_mb=10)
    assert validator.max_file_size == 10 * 1024 * 1024


def test_dashboard_max_upload_size_uses_settings():
    from app.routers import views
    assert views.DASHBOARD_MAX_UPLOAD_SIZE == settings.MAX_UPLOAD_SIZE
