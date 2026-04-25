"""Async wrapper over tapi-yandex-direct."""

import asyncio
import logging
from datetime import date
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


class YandexDirectError(Exception):
    """Raised on Yandex Direct API errors."""


class YandexDirectClient:
    """Async client for Yandex Direct API via tapi-yandex-direct."""

    def __init__(self, settings: Settings) -> None:
        self._token = settings.yandex_direct_token
        self._login = settings.yandex_direct_login

    def _get_api(self) -> Any:
        from tapi_yandex_direct import YandexDirect  # lazy import: not installed in tests

        return YandexDirect(access_token=self._token, login=self._login, is_sandbox=False)

    async def list_campaigns(self) -> list[dict[str, Any]]:
        """Return all campaigns for the account."""

        def _call() -> list[dict[str, Any]]:
            api = self._get_api()
            result = api.campaigns().get(
                data={
                    "method": "get",
                    "params": {
                        "SelectionCriteria": {},
                        "FieldNames": ["Id", "Name", "Status", "Type"],
                    },
                }
            )
            return result().data.get("result", {}).get("Campaigns", [])

        try:
            return await asyncio.to_thread(_call)
        except Exception as exc:
            raise YandexDirectError(f"list_campaigns failed: {exc}") from exc

    async def get_campaign(self, campaign_id: int) -> dict[str, Any]:
        """Return single campaign by ID."""

        def _call() -> dict[str, Any]:
            api = self._get_api()
            result = api.campaigns().get(
                data={
                    "method": "get",
                    "params": {
                        "SelectionCriteria": {"Ids": [campaign_id]},
                        "FieldNames": ["Id", "Name", "Status", "Type", "DailyBudget"],
                    },
                }
            )
            campaigns = result().data.get("result", {}).get("Campaigns", [])
            if not campaigns:
                raise YandexDirectError(f"Campaign {campaign_id} not found")
            return campaigns[0]

        try:
            return await asyncio.to_thread(_call)
        except YandexDirectError:
            raise
        except Exception as exc:
            raise YandexDirectError(f"get_campaign failed: {exc}") from exc

    async def create_campaign(self, config: dict[str, Any]) -> int:
        """Create campaign from config dict; return external campaign ID."""

        def _call() -> int:
            api = self._get_api()
            result = api.campaigns().add(data={"method": "add", "params": {"Campaigns": [config]}})
            ids = result().data.get("result", {}).get("AddResults", [])
            if not ids or "Id" not in ids[0]:
                raise YandexDirectError("No campaign ID returned")
            return ids[0]["Id"]

        try:
            return await asyncio.to_thread(_call)
        except YandexDirectError:
            raise
        except Exception as exc:
            raise YandexDirectError(f"create_campaign failed: {exc}") from exc

    async def update_keywords(self, campaign_id: int, keywords: list[str]) -> None:
        """Replace ad group keywords for a campaign."""

        def _call() -> Any:
            api = self._get_api()
            kw_objects = [
                {"Keyword": kw, "BidCeiling": {"value": 100, "currency": "RUB"}} for kw in keywords
            ]
            result = api.keywords().add(
                data={
                    "method": "add",
                    "params": {"Keywords": [{"AdGroupId": campaign_id, **kw} for kw in kw_objects]},
                }
            )
            return result().data

        try:
            await asyncio.to_thread(_call)
        except Exception as exc:
            raise YandexDirectError(f"update_keywords failed: {exc}") from exc

    async def pause_campaign(self, campaign_id: int) -> None:
        """Pause a running campaign."""

        def _call() -> Any:
            api = self._get_api()
            result = api.campaigns().suspend(
                data={
                    "method": "suspend",
                    "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
                }
            )
            return result().data

        try:
            await asyncio.to_thread(_call)
        except Exception as exc:
            raise YandexDirectError(f"pause_campaign failed: {exc}") from exc

    async def resume_campaign(self, campaign_id: int) -> None:
        """Resume a paused campaign."""

        def _call() -> Any:
            api = self._get_api()
            result = api.campaigns().resume(
                data={
                    "method": "resume",
                    "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
                }
            )
            return result().data

        try:
            await asyncio.to_thread(_call)
        except Exception as exc:
            raise YandexDirectError(f"resume_campaign failed: {exc}") from exc

    async def get_report(
        self, date_from: date, date_to: date, fields: list[str]
    ) -> list[dict[str, Any]]:
        """Fetch performance report for date range."""

        def _call() -> list[dict[str, Any]]:
            api = self._get_api()
            result = api.reports().get(
                data={
                    "method": "get",
                    "params": {
                        "SelectionCriteria": {
                            "DateFrom": date_from.isoformat(),
                            "DateTo": date_to.isoformat(),
                        },
                        "FieldNames": fields,
                        "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
                        "DateRangeType": "CUSTOM_DATE",
                        "Format": "TSV",
                        "IncludeVAT": "YES",
                        "IncludeDiscount": "NO",
                    },
                }
            )
            return result().data

        try:
            return await asyncio.to_thread(_call)
        except Exception as exc:
            raise YandexDirectError(f"get_report failed: {exc}") from exc
