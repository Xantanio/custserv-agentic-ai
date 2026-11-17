from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = Field(default="development", description="Execution environment")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # PostgreSQL Database
    POSTGRES_USER: str = Field(default="omniops")
    POSTGRES_PASSWORD: str = Field(default="omniops_secret")
    POSTGRES_DB: str = Field(default="omniops_db")
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)
    DATABASE_URL: Optional[str] = Field(
        default=None,
        description="Async SQLAlchemy database connection URL (e.g. postgresql+asyncpg://...)",
    )

    # API & Webhooks
    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(default=8000)

    # MCP Server
    MCP_SERVER_HOST: str = Field(default="0.0.0.0")
    MCP_SERVER_PORT: int = Field(default=8001)
    MCP_SERVER_URL: str = Field(default="http://localhost:8001")

    # Streamlit UI
    STREAMLIT_PORT: int = Field(default=8501)

    # A2A / Internal Liaison
    SLACK_WEBHOOK_URL: str = Field(
        default="https://hooks.slack.com/services/MOCK/A2A/SPECIALISTS",
        description="Internal notification webhook for operations/engineering specialists",
    )

    # LLM Provider
    OPENAI_API_KEY: str = Field(default="mock-openai-key")
    OPENAI_BASE_URL: Optional[str] = Field(default=None)
    LLM_MODEL: str = Field(default="gpt-4o-mini")

    def get_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()
