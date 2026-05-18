"""
교사/예비교사 지역 옵션 구성 검증.

issue #70: TEACHER_REGIONS 끝에 '기타' 추가, PRESERVICE_UNIVERSITY_REGIONS는
'…교대' 형식 + '기타'로 재구성. '한국교원대'는 제거.
"""
from app.constants import (
    PRESERVICE_UNIVERSITY_REGIONS,
    TEACHER_REGIONS,
)


def test_teacher_regions_ends_with_etc():
    """TEACHER_REGIONS의 마지막 원소는 '기타'."""
    assert TEACHER_REGIONS[-1] == "기타"


def test_teacher_regions_contains_legacy_sido():
    """기존 17개 시·도가 유지된다."""
    expected = [
        "서울", "부산", "대구", "인천", "광주", "대전", "울산",
        "세종", "경기", "충북", "충남", "전북", "전남", "경북",
        "경남", "강원", "제주",
    ]
    for region in expected:
        assert region in TEACHER_REGIONS


def test_preservice_regions_ends_with_etc():
    """PRESERVICE_UNIVERSITY_REGIONS의 마지막 원소는 '기타'."""
    assert PRESERVICE_UNIVERSITY_REGIONS[-1] == "기타"


def test_preservice_regions_excludes_kornu():
    """'한국교원대'는 예비교사 목록에서 제거되었다."""
    assert "한국교원대" not in PRESERVICE_UNIVERSITY_REGIONS


def test_preservice_regions_use_kyodae_suffix():
    """비-'기타' 항목은 모두 '교대'로 끝난다."""
    non_etc = [v for v in PRESERVICE_UNIVERSITY_REGIONS if v != "기타"]
    assert non_etc, "기타 외 항목이 비어 있으면 안 된다"
    for value in non_etc:
        assert value.endswith("교대"), (
            f"'{value}'는 '교대'로 끝나야 한다"
        )


def test_preservice_regions_expected_list():
    """예비교사 목록은 10개 교대 + '기타' 총 11개."""
    expected = [
        "서울교대", "경인교대", "공주교대", "광주교대", "대구교대",
        "부산교대", "전주교대", "진주교대", "청주교대", "춘천교대",
        "기타",
    ]
    assert PRESERVICE_UNIVERSITY_REGIONS == expected
