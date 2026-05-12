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


def test_accepts_korean():
    req = UpdateDisplayAliasRequest(display_alias="평가기준-1")
    assert req.display_alias == "평가기준-1"


def test_accepts_pure_korean():
    req = UpdateDisplayAliasRequest(display_alias="수학기준")
    assert req.display_alias == "수학기준"


def test_rejects_hangul_fillers():
    for alias in ("ㅤ", "ᅟ", "ᅠ", "ㅤᅟ"):
        with pytest.raises(ValidationError):
            UpdateDisplayAliasRequest(display_alias=alias)


def test_rejects_emoji():
    with pytest.raises(ValidationError):
        UpdateDisplayAliasRequest(display_alias="alias-🎯")


def test_rejects_over_255_chars():
    with pytest.raises(ValidationError) as exc_info:
        UpdateDisplayAliasRequest(display_alias="a" * 256)
    assert "255" in str(exc_info.value)


def test_accepts_exactly_255_chars():
    s = "a" * 255
    req = UpdateDisplayAliasRequest(display_alias=s)
    assert req.display_alias == s


def test_rejects_control_characters():
    with pytest.raises(ValidationError):
        UpdateDisplayAliasRequest(display_alias="a\x00b")
    with pytest.raises(ValidationError):
        UpdateDisplayAliasRequest(display_alias="line1\nline2")


def test_accepts_mixed_korean_and_ascii():
    req = UpdateDisplayAliasRequest(
        display_alias="Math 수학 grade-6"
    )
    assert req.display_alias == "Math 수학 grade-6"


def test_rejects_hanja_kanji():
    """한자(CJK 통합)는 한글이 아니므로 거부되어야 한다."""
    with pytest.raises(ValidationError):
        UpdateDisplayAliasRequest(display_alias="数学")


def test_rejects_hiragana():
    """일본어 히라가나는 한글이 아니므로 거부되어야 한다."""
    with pytest.raises(ValidationError):
        UpdateDisplayAliasRequest(display_alias="ひらがな")
