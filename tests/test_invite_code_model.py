"""
초대 코드 모델 테스트
모델 임포트 및 필드 검증
"""
import pytest

from app.models.invite_codes import InviteCode
from app.db import Base


class TestInviteCodeModel:
    """InviteCode 모델 테스트"""

    def test_model_import(self):
        """모델 임포트 테스트"""
        assert InviteCode is not None

    def test_model_tablename(self):
        """테이블명 확인"""
        assert InviteCode.__tablename__ == "invite_codes"

    def test_model_has_required_fields(self):
        """필수 필드 존재 확인"""
        columns = [
            c.name for c in InviteCode.__table__.columns
        ]
        assert "id" in columns
        assert "code" in columns
        assert "user_type" in columns
        assert "user_id" in columns
        assert "created_by" in columns
        assert "is_active" in columns
        assert "created_at" in columns
        assert "used_at" in columns

    def test_model_relationships(self):
        """관계 매핑 확인"""
        # relationships 속성 접근
        rels = InviteCode.__mapper__.relationships
        rel_keys = [r.key for r in rels]
        assert "user" in rel_keys
        assert "creator" in rel_keys

    def test_model_repr(self):
        """문자열 표현 확인"""
        invite = InviteCode(
            code="ABC123",
            user_type="1학년",
            created_by=1,
        )
        repr_str = repr(invite)
        assert "InviteCode" in repr_str
        assert "ABC123" in repr_str
        assert "1학년" in repr_str
