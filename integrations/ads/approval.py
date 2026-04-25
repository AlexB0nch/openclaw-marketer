"""Campaign approval workflow via Telegram inline keyboard."""

import datetime
import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from integrations.yandex_direct.client import YandexDirectClient

logger = logging.getLogger(__name__)

CALLBACK_APPROVE = "ads_approve"
CALLBACK_EDIT = "ads_edit"
CALLBACK_REJECT = "ads_reject"


class AdsApprovalManager:
    """Sends campaign drafts to Telegram for human approval."""

    async def send_campaign_approval(
        self,
        session: AsyncSession,
        bot: Bot,
        chat_id: str,
        campaign_id: int,
    ) -> None:
        """Send campaign draft summary to Telegram with approve/edit/reject buttons."""
        row = await session.execute(
            text("SELECT config_json, budget_rub, platform FROM ad_campaigns WHERE id = :id"),
            {"id": campaign_id},
        )
        record = row.fetchone()
        if not record:
            raise ValueError(f"Campaign {campaign_id} not found")

        config_json, budget_rub, platform = record
        config = json.loads(config_json)

        # Build summary message
        name = config.get("name", f"Campaign #{campaign_id}")
        keywords = config.get("keywords", [])[:10]
        ads = config.get("ads", [])

        text_parts = [
            f"\U0001f4e2 *Новая рекламная кампания #{campaign_id}*\n",
            f"*Название:* {name}",
            f"*Платформа:* {platform.upper()}",
            f"*Бюджет:* {budget_rub:,.0f} \u20bd",
            (
                f"*Ключевые слова* ({len(keywords)}): "
                f"{', '.join(keywords[:5])}{'...' if len(keywords) > 5 else ''}"
            ),
            "\n*Варианты объявлений:*",
        ]
        for i, ad in enumerate(ads[:3], 1):
            text_parts.append(
                f"\n*Вариант {i}:*\n"
                f"  Заголовок 1: {ad.get('title1', '')}\n"
                f"  Заголовок 2: {ad.get('title2', '')}\n"
                f"  Текст: {ad.get('text', '')}"
            )

        message_text = "\n".join(text_parts)

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "\u2705 Запустить",
                        callback_data=f"{CALLBACK_APPROVE}:{campaign_id}",
                    ),
                    InlineKeyboardButton(
                        "\u270f\ufe0f Редактировать",
                        callback_data=f"{CALLBACK_EDIT}:{campaign_id}",
                    ),
                    InlineKeyboardButton(
                        "\u274c Отклонить",
                        callback_data=f"{CALLBACK_REJECT}:{campaign_id}",
                    ),
                ]
            ]
        )

        try:
            await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            # Log approval request
            await session.execute(
                text(
                    "INSERT INTO ad_approvals (campaign_id, action, actor, reason, timestamp) "
                    "VALUES (:cid, 'approval_sent', 'system', 'Approval request sent', :ts)"
                ),
                {"cid": campaign_id, "ts": datetime.datetime.now(datetime.UTC).isoformat()},
            )
            await session.execute(
                text("UPDATE ad_campaigns SET status = 'pending_approval' WHERE id = :id"),
                {"id": campaign_id},
            )
            await session.commit()
        except TelegramError as exc:
            logger.error(
                "Failed to send approval request for campaign %d: %s",
                campaign_id,
                exc,
            )
            raise

    async def handle_approval_callback(
        self,
        session: AsyncSession,
        yandex_client: YandexDirectClient,
        campaign_id: int,
        actor: str = "admin",
    ) -> None:
        """Launch campaign after human approval."""
        # Verify status is pending_approval before launching
        row = await session.execute(
            text("SELECT status, config_json, platform FROM ad_campaigns WHERE id = :id"),
            {"id": campaign_id},
        )
        record = row.fetchone()
        if not record:
            raise ValueError(f"Campaign {campaign_id} not found")

        status, config_json, platform = record
        if status != "pending_approval":
            raise ValueError(f"Campaign {campaign_id} status is '{status}', not 'pending_approval'")

        # For Yandex campaigns, create via API
        if platform == "yandex":
            config = json.loads(config_json)
            campaign_api_config = {
                "Name": config.get("name", f"Campaign {campaign_id}"),
                "Type": "TEXT_CAMPAIGN",
                "DailyBudget": {
                    "Amount": int(config.get("budget_rub", 0) * 1_000_000 / 30),
                    "Mode": "STANDARD",
                },
            }
            external_id = await yandex_client.create_campaign(campaign_api_config)
            await session.execute(
                text(
                    "UPDATE ad_campaigns SET status = 'running', "
                    "campaign_id_external = :ext_id, launched_at = :ts "
                    "WHERE id = :id"
                ),
                {
                    "ext_id": str(external_id),
                    "ts": datetime.datetime.now(datetime.UTC).isoformat(),
                    "id": campaign_id,
                },
            )
        else:
            await session.execute(
                text(
                    "UPDATE ad_campaigns SET status = 'running', launched_at = :ts "
                    "WHERE id = :id"
                ),
                {"ts": datetime.datetime.now(datetime.UTC).isoformat(), "id": campaign_id},
            )

        await session.execute(
            text(
                "INSERT INTO ad_approvals (campaign_id, action, actor, reason, timestamp) "
                "VALUES (:cid, 'approved', :actor, 'Campaign approved and launched', :ts)"
            ),
            {
                "cid": campaign_id,
                "actor": actor,
                "ts": datetime.datetime.now(datetime.UTC).isoformat(),
            },
        )
        await session.commit()
        logger.info("Campaign %d approved and launched by %s", campaign_id, actor)

    async def handle_rejection_callback(
        self,
        session: AsyncSession,
        campaign_id: int,
        reason: str = "",
        actor: str = "admin",
    ) -> None:
        """Mark campaign as rejected."""
        await session.execute(
            text("UPDATE ad_campaigns SET status = 'rejected' WHERE id = :id"),
            {"id": campaign_id},
        )
        await session.execute(
            text(
                "INSERT INTO ad_approvals (campaign_id, action, actor, reason, timestamp) "
                "VALUES (:cid, 'rejected', :actor, :reason, :ts)"
            ),
            {
                "cid": campaign_id,
                "actor": actor,
                "reason": reason or "Rejected by admin",
                "ts": datetime.datetime.now(datetime.UTC).isoformat(),
            },
        )
        await session.commit()
        logger.info("Campaign %d rejected by %s", campaign_id, actor)
