"""display_alias 검증 스키마 테스트"""
import pytest
from pydantic import ValidationError

from app.schemas.criteria import UpdateDisplayAliasRequest


def test_accepts_ascii():
    req = UpdateDisplayAliasRequest(display_alias="elementary-6-math")
    assert req.display_alias == "elementary-6-math"


def test_strips_whitespace():
    req = UpdateDisplayAliasRequest(display_alias="  alias-1  ")
    assert req.display_alias == "alias-1"


def test_empty_string_becomes_none():
    req = UpdateDisplayAliasRequest(display_alias="")
    assert req.display_alias is None


def test_whitespace_only_becomes_none():
    req = UpdateDisplayAliasRequest(display_alias="   ")
    assert req.display_alias is None


def test_none_stays_none():
    req = UpdateDisplayAliasRequest(display_alias=None)
    assert req.display_alias is None


def test_rejects_korean():
    with pytest.raises(ValidationError) as exc_info:
        UpdateDisplayAliasRequest(display_alias="평가기준-1")
    assert "ASCII" in str(exc_info.value)


def test_rejects_emoji():
    with pytest.raises(ValidationError):
        UpdateDisplayAliasRequest(display_alias="alias-🎯")


def test_rejects_over_255_chars():
    with pytest.raises(ValidationError) as exc_info:
        UpdateDisplayAliasRequest(display_alias="a" * 256)
    assert "255" in str(exc_info.value)
