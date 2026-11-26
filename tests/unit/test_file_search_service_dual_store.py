"""
FileSearchService - get_dual_store_ids() 메서드 테스트
Phase 1에서 추가된 공통 유틸리티 메서드 검증
"""

import time
from unittest.mock import Mock, patch

import httpx
import pytest
from google.genai import errors as genai_errors

from app.config import Settings, settings
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
                mock_rubric.display_name = settings.FS_RUBRIC_STORE_NAME
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
                mock_rubric.display_name = settings.FS_RUBRIC_STORE_NAME
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
                mock_rubric.display_name = settings.FS_RUBRIC_STORE_NAME
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


RUBRIC = _store(settings.FS_RUBRIC_STORE_NAME, "fileSearchStores/rubric")
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


# 스토어 삭제: 실패를 올린다. 조회만 다시 부르고 삭제는 한 번만 부른다 (#466)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        _timeout,
        lambda: genai_errors.ServerError(503, {"error": {"code": 503}}),
    ],
    ids=["timeout", "503"],
)
async def test_delete_store_raises_when_delete_fails(service, sleeps, error):
    service.client.file_search_stores.list.return_value = [RUBRIC, USER]
    service.client.file_search_stores.delete.side_effect = error()

    with pytest.raises(type(error())):
        await service.delete_store_by_display_name("user-7-store")

    service.client.file_search_stores.delete.assert_called_once_with(
        name=USER.name, config={"force": True}
    )
    assert sleeps == []


@pytest.mark.asyncio
async def test_delete_store_raises_when_lookup_fails(service, sleeps):
    service.client.file_search_stores.list.side_effect = lambda **kw: (
        _ for _ in ()
    ).throw(_timeout())

    with pytest.raises(httpx.ReadTimeout):
        await service.delete_store_by_display_name("user-7-store")

    assert service.client.file_search_stores.list.call_count == 3
    service.client.file_search_stores.list.assert_called_with(
        config=LIST_CONFIG
    )
    assert sleeps == [2.0, 4.0]
    service.client.file_search_stores.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_store_retries_lookup_then_deletes_once(service, sleeps):
    service.client.file_search_stores.list.side_effect = [
        _timeout(),
        [RUBRIC, USER],
    ]

    await service.delete_store_by_display_name("user-7-store")

    service.client.file_search_stores.delete.assert_called_once_with(
        name=USER.name, config={"force": True}
    )
    assert sleeps == [2.0]


@pytest.mark.asyncio
async def test_delete_store_without_store_does_not_raise(service, sleeps):
    service.client.file_search_stores.list.return_value = [RUBRIC]

    assert await service.delete_store_by_display_name("user-7-store") is None

    service.client.file_search_stores.delete.assert_not_called()


def test_store_creation_is_not_retried(service, sleeps):
    service.client.file_search_stores.list.return_value = [RUBRIC]
    service.client.file_search_stores.create.side_effect = (
        httpx.RemoteProtocolError("Server disconnected")
    )

    with pytest.raises(httpx.RemoteProtocolError):
        service.get_dual_store_ids(7)

    assert service.client.file_search_stores.create.call_count == 1
    assert service._store_cache == {}


# 평가기준 스토어는 설정 이름과 정확히 같은 것만 쓴다 (#470)
PROD_RUBRIC = _store("rubric-store", "fileSearchStores/prod-rubric")
DEV_RUBRIC = _store("dev-rubric-store", "fileSearchStores/dev-rubric")
BOTH_ORDERS = pytest.mark.parametrize(
    "listing",
    [[PROD_RUBRIC, DEV_RUBRIC, USER], [USER, DEV_RUBRIC, PROD_RUBRIC]],
)


@BOTH_ORDERS
def test_rubric_store_is_the_one_named_in_settings(
    service, monkeypatch, listing
):
    monkeypatch.setattr(settings, "FS_RUBRIC_STORE_NAME", "dev-rubric-store")
    service.client.file_search_stores.list.return_value = listing

    assert service.get_dual_store_ids(7) == [USER.name, DEV_RUBRIC.name]


@BOTH_ORDERS
def test_default_setting_uses_rubric_store(service, monkeypatch, listing):
    default = Settings.model_fields["FS_RUBRIC_STORE_NAME"].default
    monkeypatch.setattr(settings, "FS_RUBRIC_STORE_NAME", default)
    service.client.file_search_stores.list.return_value = listing

    assert service.get_dual_store_ids(7) == [USER.name, PROD_RUBRIC.name]


def test_missing_rubric_store_does_not_fall_back_to_a_similar_name(
    service, monkeypatch
):
    monkeypatch.setattr(settings, "FS_RUBRIC_STORE_NAME", "dev-rubric-store")
    similar = [
        "rubric-store",
        "rubricstore",
        "Dev-Rubric-Store",
        "dev_rubric_store",
    ]
    service.client.file_search_stores.list.return_value = [
        _store(name, f"fileSearchStores/other{i}")
        for i, name in enumerate(similar)
    ] + [USER]

    with pytest.raises(ValueError, match="평가기준 스토어"):
        service.get_dual_store_ids(7)

    assert service._store_cache == {}
    service.client.file_search_stores.create.assert_not_called()
