"""#374: 문서 목록은 file_search_stores.documents.list(parent=...)로 가져온다.

가짜 client는 google-genai 1.60.0의 실제 인터페이스(spec)만 가진다.
없는 list_documents를 부르면 AttributeError가 난다.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.genai.documents import Documents
from google.genai.file_search_stores import FileSearchStores

from app.services.lessonplan_analysis_service import LessonPlanAnalysisService
from app.services.lessonplan_vector_service import LessonPlanVectorService


def _doc(name, display_name):
    return SimpleNamespace(name=name, display_name=display_name)


def _fake_service(store_display_name, docs):
    store = SimpleNamespace(
        display_name=store_display_name, name="fileSearchStores/s1"
    )
    stores = Mock(spec=FileSearchStores)
    stores.list.return_value = [store]
    stores.documents = Mock(spec=Documents)
    stores.documents.list.return_value = docs
    return SimpleNamespace(client=SimpleNamespace(file_search_stores=stores))


def _analysis_service(fake):
    svc = LessonPlanAnalysisService.__new__(LessonPlanAnalysisService)
    svc.file_search_service = fake
    return svc


def _vector_service(fake):
    svc = LessonPlanVectorService.__new__(LessonPlanVectorService)
    svc.file_search_service = fake
    return svc


def test_fake_client_has_no_list_documents():
    stores = _fake_service("user-1-store", []).client.file_search_stores
    with pytest.raises(AttributeError):
        stores.list_documents


def test_user_store_has_documents_true_with_one_document():
    fake = _fake_service("user-1-store", [_doc("d1", "a.pdf")])
    assert _analysis_service(fake)._user_file_search_store_has_documents(1)
    fake.client.file_search_stores.documents.list.assert_called_once_with(
        parent="fileSearchStores/s1"
    )


def test_user_store_has_documents_false_with_empty_page():
    fake = _fake_service("user-1-store", [])
    svc = _analysis_service(fake)
    assert svc._user_file_search_store_has_documents(1) is False


@pytest.mark.asyncio
async def test_list_user_documents_uses_documents_list():
    fake = _fake_service(
        "user-7-store", [_doc("d1", "a.pdf"), _doc("d2", "b.pdf")]
    )
    docs = await _vector_service(fake).list_user_documents(7)
    assert docs == [
        {"document_id": "d1", "display_name": "a.pdf"},
        {"document_id": "d2", "display_name": "b.pdf"},
    ]
    fake.client.file_search_stores.documents.list.assert_called_once_with(
        parent="fileSearchStores/s1"
    )


@pytest.mark.asyncio
async def test_cleanup_expired_sessions_deletes_empty_store():
    fake = _fake_service("user-7-store", [])
    deleted = await _vector_service(fake).cleanup_expired_sessions()
    assert deleted == 1
    fake.client.file_search_stores.delete.assert_called_once_with(
        name="fileSearchStores/s1"
    )


@pytest.mark.asyncio
async def test_cleanup_expired_sessions_keeps_store_with_documents():
    fake = _fake_service("user-7-store", [_doc("d1", "a.pdf")])
    assert await _vector_service(fake).cleanup_expired_sessions() == 0
    fake.client.file_search_stores.delete.assert_not_called()
