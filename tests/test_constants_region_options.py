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


def test_preservice_regions_includes_kornu():
    """'한국교원대'는 예비교사 목록에 포함되어 있다 (이슈 #72)."""
    assert "한국교원대" in PRESERVICE_UNIVERSITY_REGIONS


def test_preservice_regions_kornu_before_etc():
    """'한국교원대'는 '기타' 바로 앞에 위치한다."""
    idx_kornu = PRESERVICE_UNIVERSITY_REGIONS.index("한국교원대")
    idx_etc = PRESERVICE_UNIVERSITY_REGIONS.index("기타")
    assert idx_etc == idx_kornu + 1


def test_preservice_regions_kyodae_items_use_suffix():
    """'한국교원대'와 '기타'를 제외한 항목은 모두 '교대'로 끝난다."""
    special = {"한국교원대", "기타"}
    non_special = [
        v for v in PRESERVICE_UNIVERSITY_REGIONS if v not in special
    ]
    assert non_special, "교대 항목이 비어 있으면 안 된다"
    for value in non_special:
        assert value.endswith("교대"), (
            f"'{value}'는 '교대'로 끝나야 한다"
        )


def test_preservice_regions_expected_list():
    """예비교사 목록은 10개 교대 + 한국교원대 + '기타' 총 12개."""
    expected = [
        "서울교대", "경인교대", "공주교대", "광주교대", "대구교대",
        "부산교대", "전주교대", "진주교대", "청주교대", "춘천교대",
        "한국교원대",
        "기타",
    ]
    assert PRESERVICE_UNIVERSITY_REGIONS == expected
