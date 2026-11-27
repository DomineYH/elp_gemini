"""
FileSearchService - 스토어 조회·삭제 테스트
평가기준 스토어는 설정 이름으로, 사용자 스토어는 자원 이름으로만 다룬다 (#470)
"""

import time
from unittest.mock import Mock, patch

import httpx
import pytest
from google.genai import errors as genai_errors

from app.config import Settings, settings
from app.services.file_search_service import (
    FileSearchService,
    RubricStoreNotFound,
)
from app.utils.gemini_retry import GeminiQuotaExhausted, GeminiServerOverloaded


class TestGetRubricStoreId:
    """
    get_rubric_store_id() 메서드 테스트
    """

    def test_get_rubric_store_id_success(self):
        """
        같은 이름표의 사용자 스토어가 있어도 평가기준 스토어만 돌려준다
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
                result = service.get_rubric_store_id()

                # Then
                assert result == "fileSearchStores/rubric123"

    def test_get_rubric_store_id_no_rubricstore(self):
        """
        rubricstore 없을 시 RubricStoreNotFound 발생
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
                with pytest.raises(RubricStoreNotFound) as exc_info:
                    service.get_rubric_store_id()

                assert "rubricstore" in str(exc_info.value)

    def test_get_rubric_store_id_caching(self):
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
                result1 = service.get_rubric_store_id()
                calls_after_first = (
                    service.client.file_search_stores.list.call_count
                )
                result2 = service.get_rubric_store_id()

                # Then
                assert result1 == result2
                # 두 번째 호출은 캐시 히트 → list() 추가 호출 없음
                assert (
                    service.client.file_search_stores.list.call_count
                    == calls_after_first
                )

    @pytest.mark.asyncio
    async def test_delete_store_force_true(self):
        """
        delete_store() 는 자원 이름으로, force=True 로 지운다
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
                await service.delete_store("fileSearchStores/test123")

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


def test_rubric_lookup_lists_once_with_request_timeout(service, sleeps):
    service.client.file_search_stores.list.return_value = [RUBRIC, USER]

    assert service.get_rubric_store_id() == RUBRIC.name

    service.client.file_search_stores.list.assert_called_once_with(
        config=LIST_CONFIG
    )
    assert sleeps == []


# 사용자 스토어: 행의 자원 이름으로 GET 1회. 목록 조회도 생성도 없다 (#470)
def test_store_exists_gets_once_with_request_timeout(service, sleeps):
    assert service.store_exists(USER.name) is True

    service.client.file_search_stores.get.assert_called_once_with(
        name=USER.name, config=LIST_CONFIG
    )
    service.client.file_search_stores.list.assert_not_called()
    service.client.file_search_stores.create.assert_not_called()
    assert sleeps == []


@pytest.mark.parametrize("code", [404, 403])
def test_store_exists_is_false_for_a_store_gone_in_the_cloud(
    service, sleeps, code
):
    service.client.file_search_stores.get.side_effect = (
        genai_errors.ClientError(code, {"error": {"code": code}})
    )

    assert service.store_exists(USER.name) is False

    assert service.client.file_search_stores.get.call_count == 1
    service.client.file_search_stores.create.assert_not_called()


def test_store_exists_raises_other_client_errors(service, sleeps):
    service.client.file_search_stores.get.side_effect = (
        genai_errors.ClientError(400, {"error": {"code": 400}})
    )

    with pytest.raises(genai_errors.ClientError):
        service.store_exists(USER.name)


def test_store_exists_retries_a_timeout_then_gives_up(service, sleeps):
    service.client.file_search_stores.get.side_effect = lambda **kw: (
        _ for _ in ()
    ).throw(_timeout())

    with pytest.raises(httpx.ReadTimeout):
        service.store_exists(USER.name)

    assert service.client.file_search_stores.get.call_count == 3
    assert sleeps == [2.0, 4.0]


def test_lookup_timeout_once_is_retried_after_2s(service, sleeps):
    service.client.file_search_stores.list.side_effect = [
        _timeout(),
        [RUBRIC, USER],
    ]

    assert service.get_rubric_store_id() == RUBRIC.name

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

    assert service.get_rubric_store_id() == RUBRIC.name
    assert service.client.file_search_stores.list.call_count == 2


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
# 사용자 스토어 GET 도 평가기준 목록 조회와 같은 재시도·변환을 거친다 (#470)
@pytest.mark.parametrize(
    "method, lookup",
    [
        ("list", lambda svc: svc.get_rubric_store_id()),
        ("get", lambda svc: svc.store_exists(USER.name)),
    ],
)
def test_lookup_gives_up_after_three_tries_and_caches_nothing(
    service, sleeps, method, lookup, error, raised
):
    sdk_call = getattr(service.client.file_search_stores, method)
    sdk_call.side_effect = lambda **kw: (_ for _ in ()).throw(error())

    with pytest.raises(raised):
        lookup(service)

    assert sdk_call.call_count == 3
    assert sleeps == [2.0, 4.0]
    assert service._store_cache == {}
    service.client.file_search_stores.create.assert_not_called()


def test_lookup_does_not_retry_permission_error(service, sleeps):
    service.client.file_search_stores.list.side_effect = (
        genai_errors.ClientError(403, {"error": {"code": 403}})
    )

    with pytest.raises(genai_errors.ClientError):
        service.get_rubric_store_id()

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
        await service.delete_store(USER.name)

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
        await service.delete_store(USER.name)

    assert service.client.file_search_stores.list.call_count == 3
    service.client.file_search_stores.list.assert_called_with(
        config=LIST_CONFIG
    )
    assert sleeps == [2.0, 4.0]
    service.client.file_search_stores.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_store_lookup_503_keeps_sdk_text_out_of_log(
    service, sleeps, caplog
):
    # 조회 재시도가 소진돼도 SDK 오류 원문은 로그에 남지 않는다 (#484)
    service.client.file_search_stores.list.side_effect = lambda **kw: (
        _ for _ in ()
    ).throw(
        genai_errors.ServerError(
            503, {"error": {"code": 503, "message": "sensitive-marker"}}
        )
    )

    with caplog.at_level("DEBUG"):
        with pytest.raises(GeminiServerOverloaded):
            await service.delete_store(USER.name)

    assert service.client.file_search_stores.list.call_count == 3
    assert "ServerError 503" in caplog.text
    assert "sensitive-marker" not in caplog.text
    service.client.file_search_stores.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_store_retries_lookup_then_deletes_once(service, sleeps):
    service.client.file_search_stores.list.side_effect = [
        _timeout(),
        [RUBRIC, USER],
    ]

    await service.delete_store(USER.name)

    service.client.file_search_stores.delete.assert_called_once_with(
        name=USER.name, config={"force": True}
    )
    assert sleeps == [2.0]


@pytest.mark.asyncio
async def test_delete_store_without_store_does_not_raise(service, sleeps):
    service.client.file_search_stores.list.return_value = [RUBRIC]

    assert await service.delete_store(USER.name) is None

    service.client.file_search_stores.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_store_ignores_a_same_name_store_of_another_deployment(
    service, sleeps
):
    # 표시 이름이 같아도 자원 이름이 다르면 남의 스토어다 (#470)
    other = _store("user-7-store", "fileSearchStores/other-deployment")
    service.client.file_search_stores.list.return_value = [RUBRIC, other]

    await service.delete_store(USER.name)

    service.client.file_search_stores.delete.assert_not_called()


# 사용자 업로드: 같은 이름의 스토어가 있어도 새로 만든다 (#470)
@pytest.mark.asyncio
async def test_user_upload_creates_a_store_without_listing(service, tmp_path):
    service.main_store_name = "main"
    created = _store("user-7-store", "fileSearchStores/new")
    service.client.file_search_stores.create.return_value = created
    operation = Mock(done=True, error=None)
    operation.response.document_name = "fileSearchStores/new/documents/d"
    operation.response.parent = "fileSearchStores/new"
    upload = service.client.file_search_stores.upload_to_file_search_store
    upload.return_value = operation
    path = tmp_path / "plan.txt"
    path.write_text("x")

    result = await service.upload_document(
        str(path), "plan.txt", {"user_id": 7}
    )

    assert result["store_id"] == "fileSearchStores/new"
    service.client.file_search_stores.create.assert_called_once_with(
        config={"display_name": "user-7-store"}
    )
    assert upload.call_args.kwargs["file_search_store_name"] == created.name
    service.client.file_search_stores.list.assert_not_called()
    service.client.file_search_stores.delete.assert_not_called()


# 생성은 재시도하지 않는다. 끊긴 요청이 이미 만들었을 수 있다 (#470)
@pytest.mark.asyncio
async def test_user_store_creation_is_not_retried(service, sleeps, tmp_path):
    service.client.file_search_stores.create.side_effect = (
        httpx.RemoteProtocolError("Server disconnected")
    )
    path = tmp_path / "plan.txt"
    path.write_text("x")

    with pytest.raises(httpx.RemoteProtocolError):
        await service.upload_document(str(path), "plan.txt", {"user_id": 7})

    service.client.file_search_stores.create.assert_called_once()
    upload = service.client.file_search_stores.upload_to_file_search_store
    upload.assert_not_called()
    service.client.file_search_stores.list.assert_not_called()
    service.client.file_search_stores.delete.assert_not_called()
    assert sleeps == []
    assert service._store_cache == {}


@pytest.mark.asyncio
async def test_rubric_upload_still_reuses_the_named_store(service, tmp_path):
    service.rubric_store_name = RUBRIC.display_name
    service.client.file_search_stores.list.return_value = [RUBRIC]
    upload = service.client.file_search_stores.upload_to_file_search_store
    upload.side_effect = RuntimeError("stop here")
    path = tmp_path / "criteria.txt"
    path.write_text("x")

    with pytest.raises(RuntimeError, match="stop here"):
        await service.upload_document(
            str(path), "criteria.txt", {"user_id": 7}, store_type="rubric"
        )

    assert upload.call_args.kwargs["file_search_store_name"] == RUBRIC.name
    service.client.file_search_stores.create.assert_not_called()
    # 평가기준 스토어는 실패해도 지우지 않는다
    service.client.file_search_stores.delete.assert_not_called()


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

    assert service.get_rubric_store_id() == DEV_RUBRIC.name


@BOTH_ORDERS
def test_default_setting_uses_rubric_store(service, monkeypatch, listing):
    default = Settings.model_fields["FS_RUBRIC_STORE_NAME"].default
    monkeypatch.setattr(settings, "FS_RUBRIC_STORE_NAME", default)
    service.client.file_search_stores.list.return_value = listing

    assert service.get_rubric_store_id() == PROD_RUBRIC.name


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

    with pytest.raises(RubricStoreNotFound, match="평가기준 스토어"):
        service.get_rubric_store_id()

    assert service._store_cache == {}
    service.client.file_search_stores.create.assert_not_called()
