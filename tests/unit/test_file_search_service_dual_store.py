"""
FileSearchService - get_dual_store_ids() 메서드 테스트
Phase 1에서 추가된 공통 유틸리티 메서드 검증
"""

import time
from unittest.mock import Mock, patch

import httpx
import pytest
from google.genai import errors as genai_errors

from app.config import settings
from app.services.file_search_service import FileSearchService
from app.utils.gemini_retry import GeminiQuotaExhausted, GeminiServerOverloaded


class TestGetDualStoreIds:
    """
    get_dual_store_ids() 메서드 테스트 (Phase 1)
    rubricstore와 사용자 스토어 조회/생성 로직 검증
    """

    def test_get_dual_store_ids_success(self):
        """
        rubricstore + 사용자 스토어 조회 성공
        """
        with patch.object(settings, "GOOGLE_API_KEY", "test-key"):
            with patch("app.services.file_search_service.genai.Client"):
                service = FileSearchService()

                # Mock stores
                mock_rubric = Mock()
                mock_rubric.display_name = "rubricstore"
                mock_rubric.name = "fileSearchStores/rubric123"

                mock_user = Mock()
                mock_user.display_name = "user-123-store"
                mock_user.name = "fileSearchStores/user123"

                service.client.file_search_stores.list = Mock(
                    return_value=[mock_rubric, mock_user]
                )

                # When
                result = service.get_dual_store_ids(user_key=123)

                # Then
                assert len(result) == 2
                assert "fileSearchStores/rubric123" in result
                assert "fileSearchStores/user123" in result

    def test_get_dual_store_ids_no_rubricstore(self):
        """
        rubricstore 없을 시 ValueError 발생
        """
        with patch.object(settings, "GOOGLE_API_KEY", "test-key"):
            with patch("app.services.file_search_service.genai.Client"):
                service = FileSearchService()

                # rubricstore 없음
                mock_other = Mock()
                mock_other.display_name = "other-store"
                mock_other.name = "fileSearchStores/other"

                service.client.file_search_stores.list = Mock(
                    return_value=[mock_other]
                )

                # When & Then
                with pytest.raises(ValueError) as exc_info:
                    service.get_dual_store_ids(user_key=123)

                assert "rubricstore" in str(exc_info.value)

    def test_get_dual_store_ids_create_user_store(self):
        """
        사용자 스토어 없을 시 자동 생성
        """
        with patch.object(settings, "GOOGLE_API_KEY", "test-key"):
            with patch("app.services.file_search_service.genai.Client"):
                service = FileSearchService()

                # rubricstore만 있음
                mock_rubric = Mock()
                mock_rubric.display_name = "rubricstore"
                mock_rubric.name = "fileSearchStores/rubric"

                service.client.file_search_stores.list = Mock(
                    return_value=[mock_rubric]
                )

                # 사용자 스토어 생성 Mock
                mock_created = Mock()
                mock_created.name = "fileSearchStores/user999"
                service._get_or_create_store = Mock(return_value=mock_created)

                # When
                result = service.get_dual_store_ids(user_key=999)

                # Then
                assert len(result) == 2
                service._get_or_create_store.assert_called_once_with(
                    "user-999-store"
                )

    def test_get_dual_store_ids_caching(self):
        """
        60초 이내 재호출 시 캐시 사용
        """
        with patch.object(settings, "GOOGLE_API_KEY", "test-key"):
            with patch("app.services.file_search_service.genai.Client"):
                service = FileSearchService()

                # Mock stores
                mock_rubric = Mock()
                mock_rubric.display_name = "rubricstore"
                mock_rubric.name = "fileSearchStores/rubric"

                mock_user = Mock()
                mock_user.display_name = "user-123-store"
                mock_user.name = "fileSearchStores/user123"

                service.client.file_search_stores.list = Mock(
                    return_value=[mock_rubric, mock_user]
                )

                # When
                result1 = service.get_dual_store_ids(user_key=123)
                calls_after_first = (
                    service.client.file_search_stores.list.call_count
                )
                result2 = service.get_dual_store_ids(user_key=123)

                # Then
                assert result1 == result2
                # 두 번째 호출은 캐시 히트 → list() 추가 호출 없음
                assert (
                    service.client.file_search_stores.list.call_count
                    == calls_after_first
                )

    @pytest.mark.asyncio
    async def test_delete_store_by_display_name_force_true(self):
        """
        delete_store_by_display_name() force=True 사용 확인
        """
        with patch.object(settings, "GOOGLE_API_KEY", "test-key"):
            with patch("app.services.file_search_service.genai.Client"):
                service = FileSearchService()

                # Mock store
                mock_store = Mock()
                mock_store.display_name = "test-store"
                mock_store.name = "fileSearchStores/test123"

                service.client.file_search_stores.list = Mock(
                    return_value=[mock_store]
                )
                service.client.file_search_stores.delete = Mock()

                # When
                await service.delete_store_by_display_name("test-store")

                # Then
                service.client.file_search_stores.delete.assert_called_once_with(
                    name=mock_store.name, config={"force": True}
                )


# 스토어 목록 조회: 요청별 10초 제한, timeout 포함 3회 시도 (#464)
LIST_CONFIG = {"http_options": {"timeout": 10_000}}


def _store(display_name, name):
    store = Mock(display_name=display_name)
    store.name = name
    return store


RUBRIC = _store("rubricstore", "fileSearchStores/rubric")
USER = _store("user-7-store", "fileSearchStores/user7")


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(time, "sleep", waited.append)
    return waited


@pytest.fixture
def service():
    with patch.object(settings, "GOOGLE_API_KEY", "test-key"):
        svc = FileSearchService.__new__(FileSearchService)
    svc._store_cache = {}
    svc.client = Mock()
    return svc


def _timeout():
    return httpx.ReadTimeout("The read operation timed out")


def test_dual_lookup_lists_once_with_request_timeout(service, sleeps):
    service.client.file_search_stores.list.return_value = [RUBRIC, USER]

    assert service.get_dual_store_ids(7) == [USER.name, RUBRIC.name]

    service.client.file_search_stores.list.assert_called_once_with(
        config=LIST_CONFIG
    )
    assert sleeps == []


def test_user_lookup_lists_once_with_request_timeout(service, sleeps):
    service.client.file_search_stores.list.return_value = [RUBRIC, USER]

    assert service.get_user_store_id(7) == USER.name

    service.client.file_search_stores.list.assert_called_once_with(
        config=LIST_CONFIG
    )


def test_lookup_timeout_once_is_retried_after_2s(service, sleeps):
    service.client.file_search_stores.list.side_effect = [
        _timeout(),
        [RUBRIC, USER],
    ]

    assert service.get_dual_store_ids(7) == [USER.name, RUBRIC.name]

    assert service.client.file_search_stores.list.call_count == 2
    assert sleeps == [2.0]


def test_lookup_failure_on_a_later_page_is_retried(service, sleeps):
    def broken_pager():
        yield RUBRIC
        raise _timeout()

    service.client.file_search_stores.list.side_effect = [
        broken_pager(),
        [RUBRIC, USER],
    ]

    assert service.get_user_store_id(7) == USER.name
    assert service.client.file_search_stores.list.call_count == 2


@pytest.mark.parametrize("method", ["get_dual_store_ids", "get_user_store_id"])
@pytest.mark.parametrize(
    "error, raised",
    [
        (_timeout, httpx.ReadTimeout),
        (
            lambda: httpx.RemoteProtocolError("Server disconnected"),
            httpx.RemoteProtocolError,
        ),
        (
            lambda: genai_errors.ServerError(503, {"error": {"code": 503}}),
            GeminiServerOverloaded,
        ),
        (
            lambda: genai_errors.ClientError(429, {"error": {"code": 429}}),
            GeminiQuotaExhausted,
        ),
    ],
)
def test_lookup_gives_up_after_three_tries_and_caches_nothing(
    service, sleeps, method, error, raised
):
    service.client.file_search_stores.list.side_effect = lambda **kw: (
        _ for _ in ()
    ).throw(error())

    with pytest.raises(raised):
        getattr(service, method)(7)

    assert service.client.file_search_stores.list.call_count == 3
    assert sleeps == [2.0, 4.0]
    assert service._store_cache == {}
    service.client.file_search_stores.create.assert_not_called()


def test_lookup_does_not_retry_permission_error(service, sleeps):
    service.client.file_search_stores.list.side_effect = (
        genai_errors.ClientError(403, {"error": {"code": 403}})
    )

    with pytest.raises(genai_errors.ClientError):
        service.get_dual_store_ids(7)

    assert service.client.file_search_stores.list.call_count == 1


def test_store_creation_is_not_retried(service, sleeps):
    service.client.file_search_stores.list.return_value = [RUBRIC]
    service.client.file_search_stores.create.side_effect = (
        httpx.RemoteProtocolError("Server disconnected")
    )

    with pytest.raises(httpx.RemoteProtocolError):
        service.get_dual_store_ids(7)

    assert service.client.file_search_stores.create.call_count == 1
    assert service._store_cache == {}
