from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Anthropic
    anthropic_api_key: str

    # Telegram
    telegram_bot_token: str
    telegram_admin_chat_id: str
    telegram_channel_id: str = ""  # Sprint 2: channel to publish content

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "aimarketing"
    postgres_user: str
    postgres_password: str

    # n8n
    n8n_webhook_url: str
    n8n_api_key: str

    # OpenClaw
    openclaw_port: int = 3000

    # Budget
    monthly_ads_budget_limit_rub: float = 100_000.0

    # Yandex Direct (Sprint 3)
    yandex_direct_token: str = ""
    yandex_direct_login: str = ""

    # Google Analytics / Ads (Sprint 3)
    google_ads_developer_token: str = ""
    google_ads_client_id: str = ""
    google_ads_client_secret: str = ""
    google_ads_refresh_token: str = ""
    google_ads_customer_id: str = ""

    # Analytics alert thresholds (Sprint 3)
    daily_spend_alert_threshold_rub: float = 5_000.0

<<<<<<< HEAD
    # Events Agent (Sprint 6)
    events_enabled: bool = False
=======
    # TG Scout (Sprint 5)
    telethon_api_id: int = 0
    telethon_api_hash: str = ""
    telethon_session_path: str = "./data/telethon.session"
    tgstat_api_key: str = ""
    monitor_keywords: str = "AI помощник,ИИ тренер,агрегатор новостей"
>>>>>>> origin/main

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
