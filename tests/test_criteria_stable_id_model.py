"""Criteria 모델에 stable_id 필드가 추가되었는지 확인"""
from app.models.criteria import Criteria


def test_criteria_model_has_stable_id_column():
    col = Criteria.__table__.columns.get("stable_id")
    assert col is not None
    assert col.nullable is True
    assert str(col.type).startswith("VARCHAR")
