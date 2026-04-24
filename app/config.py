from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Anthropic
    anthropic_api_key: str

    # Telegram
    telegram_bot_token: str
    telegram_admin_chat_id: str

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

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
