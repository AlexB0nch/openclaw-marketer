"""Async metrics collectors for Telegram, Yandex Direct, and Google Analytics."""

import logging
from datetime import date

import aiohttp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from integrations.analytics.models import MetricsRecord

logger = logging.getLogger(__name__)


async def _save_post_metrics(session: AsyncSession, record: MetricsRecord) -> None:
    """Insert a Telegram post-level metrics row."""
    await session.execute(
        text(
            "INSERT INTO post_metrics (post_id, product_id, date, views, forwards, reactions) "
            "VALUES (:post_id, :product_id, :date, :views, :forwards, :reactions)"
        ),
        {
            "post_id": record.post_id,
            "product_id": record.product_id,
            "date": str(record.date),
            "views": record.views or 0,
            "forwards": record.forwards or 0,
            "reactions": record.reactions or 0,
        },
    )
    await session.commit()


async def _upsert_metrics(session: AsyncSession, record: MetricsRecord) -> None:
    """Delete-then-insert upsert for the campaign-level metrics table."""
    if record.campaign_id is None:
        return
    await session.execute(
        text("DELETE FROM metrics WHERE campaign_id = :cid AND date = :date"),
        {"cid": record.campaign_id, "date": str(record.date)},
    )
    await session.execute(
        text(
            "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
            "VALUES (:cid, :date, :impressions, :clicks, :spend_rub, :conversions)"
        ),
        {
            "cid": record.campaign_id,
            "date": str(record.date),
            "impressions": record.impressions,
            "clicks": record.clicks,
            "spend_rub": record.spend_rub,
            "conversions": record.conversions,
        },
    )
    await session.commit()


class TelegramMetricsCollector:
    """Collect per-post Telegram metrics via Bot API.

    Note: Bot API does not expose per-message view counts.
    Channel subscriber count is used as an impressions proxy.
    For true per-message views, MTProto access (Telethon/Pyrogram) is required.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def collect_post_metrics(
        self,
        session: AsyncSession,
        post_id: int,
        telegram_message_id: int,
        product_id: int,
        date_collected: date,
    ) -> MetricsRecord | None:
        """Collect metrics for a single published Telegram post."""
        views = 0
        forwards = 0
        reactions = 0

        try:
            async with aiohttp.ClientSession() as http:
                url = (
                    f"https://api.telegram.org/bot{self._settings.telegram_bot_token}"
                    f"/getChatMemberCount"
                )
                async with http.get(
                    url, params={"chat_id": self._settings.telegram_channel_id}
                ) as resp:
                    data = await resp.json()
                    if not data.get("ok"):
                        logger.warning(
                            "Telegram API returned not-ok for post %d: %s",
                            post_id,
                            data,
                        )
                        return None
                    views = int(data.get("result", 0))
        except Exception as exc:
            logger.warning("Telegram metrics fetch failed for post %d: %s", post_id, exc)
            return None

        record = MetricsRecord(
            source="telegram",
            product_id=product_id,
            date=date_collected,
            post_id=post_id,
            views=views,
            forwards=forwards,
            reactions=reactions,
            impressions=views,
            clicks=0,
            spend_rub=0.0,
            conversions=0,
            ctr=0.0,
        )
        await _save_post_metrics(session, record)
        return record

    async def collect_all_recent(self, session: AsyncSession, days: int = 1) -> list[MetricsRecord]:
        """Collect metrics for all posts published in the last N days."""
        from datetime import timedelta

        cutoff = date.today() - timedelta(days=days)
        result = await session.execute(
            text(
                "SELECT id, product_id, telegram_message_id "
                "FROM scheduled_posts "
                "WHERE status = 'published' "
                "  AND published_at >= :cutoff "
                "  AND telegram_message_id IS NOT NULL"
            ),
            {"cutoff": str(cutoff)},
        )
        rows = result.fetchall()

        records: list[MetricsRecord] = []
        for row in rows:
            post_id, product_id, message_id = row[0], row[1], row[2]
            rec = await self.collect_post_metrics(
                session,
                post_id=post_id,
                telegram_message_id=message_id,
                product_id=product_id,
                date_collected=date.today(),
            )
            if rec:
                records.append(rec)
        return records


class YandexDirectMetricsCollector:
    """Collect campaign metrics from Yandex Direct Report API."""

    _REPORT_URL = "https://api.direct.yandex.com/json/v5/reports"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def collect(
        self,
        session: AsyncSession,
        campaign_id: int,
        product_id: int,
        date_from: date,
        date_to: date,
    ) -> list[MetricsRecord]:
        """Fetch daily campaign stats and upsert into metrics table."""
        if not self._settings.yandex_direct_token:
            logger.warning("YANDEX_DIRECT_TOKEN not set — skipping Yandex Direct collection")
            return []

        headers = {
            "Authorization": f"Bearer {self._settings.yandex_direct_token}",
            "Client-Login": self._settings.yandex_direct_login,
            "Content-Type": "application/json",
            "Accept-Language": "ru",
        }
        body = {
            "params": {
                "SelectionCriteria": {
                    "DateFrom": str(date_from),
                    "DateTo": str(date_to),
                    "CampaignIds": [campaign_id],
                },
                "FieldNames": [
                    "Date",
                    "Impressions",
                    "Clicks",
                    "Cost",
                    "Ctr",
                    "Conversions",
                ],
                "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
                "DateRangeType": "CUSTOM_DATE",
                "Format": "TSV",
                "IncludeVAT": "NO",
                "IncludeDiscount": "NO",
            }
        }

        records: list[MetricsRecord] = []
        try:
            async with (
                aiohttp.ClientSession() as http,
                http.post(self._REPORT_URL, json=body, headers=headers) as resp,
            ):
                if resp.status != 200:
                    logger.warning(
                        "Yandex Direct API returned %d for campaign %d",
                        resp.status,
                        campaign_id,
                    )
                    return []
                content = await resp.text()
        except Exception as exc:
            logger.warning("Yandex Direct request failed: %s", exc)
            return []

        # TSV format: 2 header rows, then data rows
        lines = content.strip().split("\n")
        for line in lines[2:]:
            parts = line.split("\t")
            if len(parts) < 6:
                continue
            rec_date_str, impressions_s, clicks_s, cost_s, ctr_s, conv_s = parts[:6]
            try:
                rec_date = date.fromisoformat(rec_date_str)
                # Yandex Direct cost is in microroubles (1/1,000,000 RUB)
                record = MetricsRecord(
                    source="yandex_direct",
                    product_id=product_id,
                    campaign_id=campaign_id,
                    date=rec_date,
                    impressions=int(impressions_s) if impressions_s.isdigit() else 0,
                    clicks=int(clicks_s) if clicks_s.isdigit() else 0,
                    spend_rub=float(cost_s) / 1_000_000 if cost_s else 0.0,
                    ctr=float(ctr_s) if ctr_s else 0.0,
                    conversions=int(conv_s) if conv_s.isdigit() else 0,
                )
                records.append(record)
                await _upsert_metrics(session, record)
            except (ValueError, TypeError) as exc:
                logger.warning("Failed to parse Yandex Direct row '%s': %s", line, exc)

        return records


class GoogleAnalyticsCollector:
    """Collect sessions and conversions from GA4 Data API."""

    _TOKEN_URL = "https://oauth2.googleapis.com/token"
    _REPORT_URL_TMPL = (
        "https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
    )

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _get_access_token(self) -> str:
        """Exchange OAuth2 refresh token for an access token."""
        async with (
            aiohttp.ClientSession() as http,
            http.post(
                self._TOKEN_URL,
                data={
                    "client_id": self._settings.google_ads_client_id,
                    "client_secret": self._settings.google_ads_client_secret,
                    "refresh_token": self._settings.google_ads_refresh_token,
                    "grant_type": "refresh_token",
                },
            ) as resp,
        ):
            data = await resp.json()
            return str(data.get("access_token", ""))

    async def collect(
        self,
        session: AsyncSession,
        campaign_id: int,
        product_id: int,
        date_from: date,
        date_to: date,
    ) -> list[MetricsRecord]:
        """Fetch daily GA4 sessions/conversions and upsert into metrics table."""
        if not self._settings.google_ads_customer_id:
            logger.warning("GOOGLE_ADS_CUSTOMER_ID not set — skipping GA4 collection")
            return []

        try:
            access_token = await self._get_access_token()
        except Exception as exc:
            logger.warning("GA4 token exchange failed: %s", exc)
            return []

        url = self._REPORT_URL_TMPL.format(property_id=self._settings.google_ads_customer_id)
        headers = {"Authorization": f"Bearer {access_token}"}
        body = {
            "dateRanges": [{"startDate": str(date_from), "endDate": str(date_to)}],
            "dimensions": [{"name": "date"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "conversions"},
            ],
        }

        records: list[MetricsRecord] = []
        try:
            async with (
                aiohttp.ClientSession() as http,
                http.post(url, json=body, headers=headers) as resp,
            ):
                if resp.status != 200:
                    logger.warning("GA4 API returned %d for property %s", resp.status, url)
                    return []
                data = await resp.json()
        except Exception as exc:
            logger.warning("GA4 request failed: %s", exc)
            return []

        for row in data.get("rows", []):
            dimensions = row.get("dimensionValues", [])
            metric_values = row.get("metricValues", [])
            if not dimensions or not metric_values:
                continue
            try:
                # GA4 date format: YYYYMMDD
                date_str = dimensions[0]["value"]
                rec_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
                sessions = int(metric_values[0]["value"])
                conversions = int(float(metric_values[1]["value"])) if len(metric_values) > 1 else 0

                record = MetricsRecord(
                    source="google_analytics",
                    product_id=product_id,
                    campaign_id=campaign_id,
                    date=rec_date,
                    impressions=sessions,
                    clicks=sessions,
                    spend_rub=0.0,
                    conversions=conversions,
                    ctr=0.0,
                )
                records.append(record)
                await _upsert_metrics(session, record)
            except (ValueError, TypeError, KeyError) as exc:
                logger.warning("Failed to parse GA4 row %s: %s", row, exc)

        return records
