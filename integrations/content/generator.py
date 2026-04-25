"""Content generation engine using Claude API with token-bucket rate limiting."""

import asyncio
import logging
import time

from anthropic import AsyncAnthropic

from app.config import Settings
from integrations.content.models import Platform, Post

logger = logging.getLogger(__name__)

_PLATFORM_GUIDELINES: dict[str, str] = {
    "telegram": (
        "800–1200 символов. Без заголовков. Emoji допустимы. "
        "Разбивай на короткие абзацы. Заканчивай призывом к действию."
    ),
    "habr": (
        "3000–5000 слов. Технический стиль. Заголовки H2 и H3. "
        "Добавь примеры кода где уместно. "
        "Структура: введение → проблема → решение → примеры → вывод + CTA."
    ),
    "vc.ru": (
        "1000–2000 слов. Бизнес-ориентированный стиль. "
        "Используй заголовки, конкретные факты и цифры. Заканчивай CTA."
    ),
    "linkedin": (
        "300–600 слов. Профессиональный тон. Абзацы без заголовков. "
        "Первое предложение — strong hook. Заканчивай призывом к действию."
    ),
}


class _TokenBucket:
    """Async token-bucket rate limiter for API calls."""

    def __init__(self, rate: float, capacity: float) -> None:
        self._rate = rate  # tokens / second
        self._capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Block until the requested number of tokens are available."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now
            if self._tokens < tokens:
                wait = (tokens - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= tokens


class ContentGenerator:
    """Generates platform-specific marketing content via Claude API."""

    # 1 request per 2 s by default; burst of 2 allowed
    _DEFAULT_RATE: float = 0.5
    _DEFAULT_CAPACITY: float = 2.0

    def __init__(
        self,
        settings: Settings,
        rate: float = _DEFAULT_RATE,
        capacity: float = _DEFAULT_CAPACITY,
    ) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._limiter = _TokenBucket(rate=rate, capacity=capacity)

    def _build_prompt(
        self,
        product_name: str,
        product_description: str,
        platform: Platform,
        topic: str,
    ) -> str:
        guide = _PLATFORM_GUIDELINES.get(platform, "1000 символов.")
        return (
            f"Напиши маркетинговый пост для платформы **{platform}**.\n\n"
            f"Продукт: {product_name}\n"
            f"Описание продукта: {product_description or 'не указано'}\n"
            f"Тема поста: {topic}\n\n"
            f"Требования к формату: {guide}\n\n"
            "Язык: русский (при необходимости — английский).\n"
            "Верни ТОЛЬКО текст поста без пояснений и мета-комментариев."
        )

    async def generate_post(
        self,
        product_id: int,
        product_name: str,
        product_description: str,
        platform: Platform,
        topic: str,
    ) -> Post:
        """Call Claude API to generate a platform-specific post."""
        await self._limiter.acquire()
        prompt = self._build_prompt(product_name, product_description, platform, topic)
        logger.info("Generating %s post for product %d — topic: %s", platform, product_id, topic)

        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system="Ты профессиональный контент-маркетолог. Создаёшь продающий контент.",
            messages=[{"role": "user", "content": prompt}],
        )
        body = response.content[0].text.strip()
        logger.info("Generated %s post for product %d (%d chars)", platform, product_id, len(body))

        return Post(
            platform=platform,
            topic=topic,
            body=body,
            product_id=product_id,
            product_name=product_name,
        )
