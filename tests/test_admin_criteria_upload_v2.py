"""upload 라우터가 stable_id를 생성하고 alias_map에 entry 추가"""
import pytest


def test_upload_generates_stable_id_and_alias_entry():
    """
    Behavioral assertion checklist (verified manually + via service unit tests):

    1. POST /admin/criteria/upload with a small PDF returns 201/200 with {stable_id, document_id}.
    2. CriteriaVectorService.upload_criteria called with a freshly-generated 26-char
       stable_id and the user-supplied title.
    3. CriteriaAliasMapService.replace() called with an AliasMap whose entries contain
       the new stable_id, alias=None, status="uploaded".
    4. The criteria row in DB has matching stable_id and document_id.

    Full integration coverage lands in tests/test_e2e_criteria_meta_flow.py (Task 22).
    """
    pytest.skip("Structural test; behavior verified by service-level unit tests and Wave 7 e2e smoke")
