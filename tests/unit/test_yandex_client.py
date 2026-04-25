"""Unit tests for YandexDirectClient."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from integrations.yandex_direct.client import YandexDirectClient, YandexDirectError


@pytest.fixture
def client(test_settings):
    return YandexDirectClient(test_settings)


def _make_mock_api(return_data: dict) -> MagicMock:
    """Build mock tapi-yandex-direct API that returns return_data."""
    mock_result = MagicMock()
    mock_result.return_value.data = return_data

    mock_resource = MagicMock()
    mock_resource.get = MagicMock(return_value=mock_result)
    mock_resource.add = MagicMock(return_value=mock_result)
    mock_resource.suspend = MagicMock(return_value=mock_result)
    mock_resource.resume = MagicMock(return_value=mock_result)

    mock_api = MagicMock()
    mock_api.campaigns = MagicMock(return_value=mock_resource)
    mock_api.keywords = MagicMock(return_value=mock_resource)
    mock_api.reports = MagicMock(return_value=mock_resource)
    return mock_api


@pytest.mark.asyncio
async def test_list_campaigns_returns_list(client):
    mock_api = _make_mock_api(
        {"result": {"Campaigns": [{"Id": 1, "Name": "Test", "Status": "ON"}]}}
    )
    with patch.object(client, "_get_api", return_value=mock_api):
        result = await client.list_campaigns()
    assert len(result) == 1
    assert result[0]["Id"] == 1


@pytest.mark.asyncio
async def test_get_campaign_found(client):
    mock_api = _make_mock_api(
        {"result": {"Campaigns": [{"Id": 42, "Name": "Alpha", "Status": "ON"}]}}
    )
    with patch.object(client, "_get_api", return_value=mock_api):
        result = await client.get_campaign(42)
    assert result["Id"] == 42


@pytest.mark.asyncio
async def test_get_campaign_not_found_raises(client):
    mock_api = _make_mock_api({"result": {"Campaigns": []}})
    with patch.object(client, "_get_api", return_value=mock_api), pytest.raises(YandexDirectError):
        await client.get_campaign(999)


@pytest.mark.asyncio
async def test_create_campaign_returns_id(client):
    mock_api = _make_mock_api({"result": {"AddResults": [{"Id": 123}]}})
    with patch.object(client, "_get_api", return_value=mock_api):
        campaign_id = await client.create_campaign({"Name": "Test", "Type": "TEXT_CAMPAIGN"})
    assert campaign_id == 123


@pytest.mark.asyncio
async def test_create_campaign_no_id_raises(client):
    mock_api = _make_mock_api({"result": {"AddResults": [{}]}})
    with patch.object(client, "_get_api", return_value=mock_api), pytest.raises(YandexDirectError):
        await client.create_campaign({})


@pytest.mark.asyncio
async def test_pause_campaign(client):
    mock_api = _make_mock_api({"result": {}})
    with patch.object(client, "_get_api", return_value=mock_api):
        await client.pause_campaign(1)  # should not raise


@pytest.mark.asyncio
async def test_resume_campaign(client):
    mock_api = _make_mock_api({"result": {}})
    with patch.object(client, "_get_api", return_value=mock_api):
        await client.resume_campaign(1)  # should not raise


@pytest.mark.asyncio
async def test_get_report_returns_data(client):
    mock_api = _make_mock_api([{"Date": "2026-04-01", "Clicks": 100}])
    with patch.object(client, "_get_api", return_value=mock_api):
        result = await client.get_report(date(2026, 4, 1), date(2026, 4, 7), ["Date", "Clicks"])
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_list_campaigns_api_error(client):
    def _raise() -> None:
        raise RuntimeError("network error")

    with patch.object(client, "_get_api", side_effect=_raise), pytest.raises(YandexDirectError):
        await client.list_campaigns()
