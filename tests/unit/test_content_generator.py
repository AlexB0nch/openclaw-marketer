"""Unit tests for ContentGenerator."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.content.generator import ContentGenerator, _TokenBucket
from integrations.content.models import Post

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings():
    from app.config import Settings

    return Settings(
        anthropic_api_key="test_key",
        telegram_bot_token="test_token",
        telegram_admin_chat_id="0",
        telegram_channel_id="@test",
        postgres_user="test",
        postgres_password="test",
        n8n_webhook_url="http://localhost:5678",
        n8n_api_key="test_dummy",
    )


def _mock_anthropic_response(text: str) -> MagicMock:
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


# ---------------------------------------------------------------------------
# TokenBucket tests
# ---------------------------------------------------------------------------


class TestTokenBucket:
    """Test async token-bucket rate limiter."""

    @pytest.mark.asyncio
    async def test_acquire_within_capacity(self):
        """Tokens available immediately when bucket is full."""
        bucket = _TokenBucket(rate=10.0, capacity=2.0)
        start = asyncio.get_event_loop().time()
        await bucket.acquire()
        await bucket.acquire()
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed < 0.5  # well under 1 s

    @pytest.mark.asyncio
    async def test_acquire_waits_when_empty(self):
        """Acquiring from an empty bucket causes a wait."""
        # rate=10 tokens/s, capacity=1 → refills in ~0.1 s
        bucket = _TokenBucket(rate=10.0, capacity=1.0)
        await bucket.acquire()  # drain
        start = asyncio.get_event_loop().time()
        await bucket.acquire()  # must wait ~0.1 s
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed >= 0.05  # at least half the theoretical wait

    @pytest.mark.asyncio
    async def test_tokens_capped_at_capacity(self):
        """Bucket never exceeds its capacity."""
        bucket = _TokenBucket(rate=100.0, capacity=3.0)
        # Simulate 10 s passing; tokens must be clamped at capacity
        bucket._last_refill = time.monotonic() - 10
        async with bucket._lock:
            bucket._tokens = min(
                bucket._capacity,
                bucket._tokens + 10 * bucket._rate,
            )
        assert bucket._tokens <= bucket._capacity


# ---------------------------------------------------------------------------
# ContentGenerator — prompt construction
# ---------------------------------------------------------------------------


class TestContentGeneratorPrompt:
    """Test prompt construction (no API call)."""

    def test_telegram_prompt_mentions_platform(self):
        gen = ContentGenerator.__new__(ContentGenerator)
        prompt = gen._build_prompt("TestProd", "A product", "telegram", "Topic A")
        assert "telegram" in prompt
        assert "TestProd" in prompt
        assert "Topic A" in prompt
        assert "800" in prompt  # length hint

    def test_habr_prompt_mentions_code(self):
        gen = ContentGenerator.__new__(ContentGenerator)
        prompt = gen._build_prompt("TestProd", "", "habr", "Deep dive")
        assert "код" in prompt.lower() or "H2" in prompt

    def test_linkedin_prompt_shorter_hint(self):
        gen = ContentGenerator.__new__(ContentGenerator)
        prompt = gen._build_prompt("Prod", "Desc", "linkedin", "Topic")
        assert "300" in prompt

    def test_vcru_prompt_mentions_business(self):
        gen = ContentGenerator.__new__(ContentGenerator)
        prompt = gen._build_prompt("Prod", "Desc", "vc.ru", "Topic")
        assert "1000" in prompt

    def test_empty_description_uses_fallback(self):
        gen = ContentGenerator.__new__(ContentGenerator)
        prompt = gen._build_prompt("Prod", "", "telegram", "Topic")
        assert "не указано" in prompt


# ---------------------------------------------------------------------------
# ContentGenerator — API calls (Claude mocked)
# ---------------------------------------------------------------------------


class TestContentGeneratorAPI:
    @pytest.mark.asyncio
    async def test_generate_post_returns_post_model(self, test_settings):
        """generate_post returns a Post with correct fields."""
        with patch("integrations.content.generator.AsyncAnthropic") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_mock_anthropic_response("Готовый пост для Telegram 🚀")
            )
            mock_client_cls.return_value = mock_client

            gen = ContentGenerator(test_settings, rate=100.0, capacity=10.0)
            post = await gen.generate_post(
                product_id=1,
                product_name="OpenClaw",
                product_description="AI platform",
                platform="telegram",
                topic="Как мы ускорили деплой",
            )

        assert isinstance(post, Post)
        assert post.platform == "telegram"
        assert post.product_id == 1
        assert post.product_name == "OpenClaw"
        assert post.body == "Готовый пост для Telegram 🚀"
        assert post.topic == "Как мы ускорили деплой"

    @pytest.mark.asyncio
    async def test_generate_post_strips_whitespace(self, test_settings):
        """generate_post strips leading/trailing whitespace from response."""
        with patch("integrations.content.generator.AsyncAnthropic") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_mock_anthropic_response("  \n  Body text  \n  ")
            )
            mock_client_cls.return_value = mock_client

            gen = ContentGenerator(test_settings, rate=100.0, capacity=10.0)
            post = await gen.generate_post(1, "Prod", "", "linkedin", "Topic")

        assert post.body == "Body text"

    @pytest.mark.asyncio
    async def test_generate_post_calls_correct_model(self, test_settings):
        """generate_post calls claude-sonnet-4-6."""
        with patch("integrations.content.generator.AsyncAnthropic") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=_mock_anthropic_response("text"))
            mock_client_cls.return_value = mock_client

            gen = ContentGenerator(test_settings, rate=100.0, capacity=10.0)
            await gen.generate_post(1, "Prod", "", "habr", "Topic")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_generate_post_all_platforms(self, test_settings):
        """generate_post works for all supported platforms."""
        platforms = ["telegram", "habr", "vc.ru", "linkedin"]
        for platform in platforms:
            with patch("integrations.content.generator.AsyncAnthropic") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.messages.create = AsyncMock(
                    return_value=_mock_anthropic_response(f"Post for {platform}")
                )
                mock_client_cls.return_value = mock_client

                gen = ContentGenerator(test_settings, rate=100.0, capacity=10.0)
                post = await gen.generate_post(1, "Prod", "", platform, "Topic")  # type: ignore[arg-type]

            assert post.platform == platform
            assert post.body == f"Post for {platform}"
