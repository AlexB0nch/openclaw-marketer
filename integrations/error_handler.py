"""Global error handler with Dead Letter Queue and Telegram alerts.

Sprint 7: provides last-resort safety net for scheduler jobs and agent tasks.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

_PAYLOAD_TRUNC = 300


class GlobalErrorHandler:
    """Save failed tasks to DLQ and notify admin via Telegram.

    Lazy bot pattern: Bot must be passed in, never instantiated at import time.
    handle() never re-raises — it is the last safety net.
    """

    def __init__(self, bot: Bot | None, engine: Any = None, admin_chat_id: str = "") -> None:
        self._bot = bot
        self._engine = engine
        self._admin_chat_id = admin_chat_id

    async def handle(
        self,
        agent: str,
        task: str,
        exc: Exception,
        payload: dict | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        """Save failed task to DLQ and send Telegram alert. Never re-raises."""
        payload = payload or {}
        tb = traceback.format_exc()
        logger.error("[%s] task=%s failed: %s\n%s", agent, task, exc, tb)

        # Save to DLQ
        try:
            if session is not None:
                await self._save_dlq(session, agent, task, exc, payload, tb)
            elif self._engine is not None:
                async with AsyncSession(self._engine) as new_session:
                    await self._save_dlq(new_session, agent, task, exc, payload, tb)
                    await new_session.commit()
        except Exception as save_exc:
            logger.error("Failed to save DLQ record: %s", save_exc)

        # Telegram alert
        try:
            if self._bot is not None and self._admin_chat_id:
                payload_str = json.dumps(payload, ensure_ascii=False, default=str)
                if len(payload_str) > _PAYLOAD_TRUNC:
                    payload_str = payload_str[:_PAYLOAD_TRUNC] + "..."
                now_msk = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
                msg = (
                    f"\u274c [{agent}] {task} failed\n"
                    f"Error: {exc}\n"
                    f"Payload: {payload_str}\n"
                    f"Time: {now_msk}"
                )
                await self._bot.send_message(chat_id=self._admin_chat_id, text=msg)
        except TelegramError as tg_exc:
            logger.error("Failed to send Telegram alert: %s", tg_exc)
        except Exception as tg_exc:
            logger.error("Unexpected error sending Telegram alert: %s", tg_exc)

    async def _save_dlq(
        self,
        session: AsyncSession,
        agent: str,
        task: str,
        exc: Exception,
        payload: dict,
        tb: str,
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO dead_letter_queue "
                "(agent, task, payload, error_message, traceback, attempts, status) "
                "VALUES (:agent, :task, :payload, :err, :tb, 1, 'pending')"
            ),
            {
                "agent": agent,
                "task": task,
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
                "err": str(exc)[:1000],
                "tb": tb[:5000],
            },
        )

    async def retry_pending(self, session: AsyncSession) -> int:
        """Fetch DLQ items eligible for retry and mark them retried.

        Returns count of items updated. Caller is responsible for re-scheduling
        the actual work.
        """
        try:
            result = await session.execute(
                text(
                    "SELECT id FROM dead_letter_queue " "WHERE status = 'pending' AND attempts <= 3"
                )
            )
            ids = [r[0] for r in result.fetchall()]
            if not ids:
                return 0
            for row_id in ids:
                await session.execute(
                    text(
                        "UPDATE dead_letter_queue "
                        "SET status = 'retried', attempts = attempts + 1, updated_at = now() "
                        "WHERE id = :id"
                    ),
                    {"id": row_id},
                )
            await session.commit()
            return len(ids)
        except Exception as exc:
            logger.error("retry_pending failed: %s", exc)
            return 0
