"""Interactive Telethon authorization script.

Run once (or whenever the session expires) to create a valid Telethon session
file at TELETHON_SESSION_PATH. The main app refuses to start MentionMonitor
without an authorized session.

Usage:
    docker-compose exec app python scripts/telethon_login.py
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

logger = logging.getLogger(__name__)


async def main() -> int:
    dotenv_path = os.environ.get("DOTENV_PATH")
    if dotenv_path:
        load_dotenv(dotenv_path)
    else:
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    api_id_raw = os.environ.get("TELETHON_API_ID", "").strip()
    api_hash = os.environ.get("TELETHON_API_HASH", "").strip()
    session_path = os.environ.get("TELETHON_SESSION_PATH", "./data/telethon.session").strip()

    if not api_id_raw or not api_hash:
        logger.error("TELETHON_API_ID and TELETHON_API_HASH must be set.")
        return 1

    try:
        api_id = int(api_id_raw)
    except ValueError:
        logger.error("TELETHON_API_ID must be int, got %r.", api_id_raw)
        return 1

    client = TelegramClient(session_path, api_id, api_hash)
    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            username = getattr(me, "username", None) or getattr(me, "first_name", "<unknown>")
            logger.info("Already authorized as %s", username)
            return 0

        phone = os.environ.get("TELEGRAM_LOGIN_PHONE", "").strip()
        if not phone:
            phone = input("Phone number (e.g. +79XXXXXXXXX): ").strip()

        await client.send_code_request(phone)
        code = input("Code from Telegram: ").strip()

        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            password = input("2FA password: ")
            await client.sign_in(password=password)

        me = await client.get_me()
        username = getattr(me, "username", None) or getattr(me, "first_name", "<unknown>")
        logger.info("Authorized as %s. Session saved to %s", username, session_path)
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(asyncio.run(main()))
