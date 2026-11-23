from typing import Literal, Optional

from pydantic import Field, SecretStr
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

    # LLM (D13/D19): provedor trocável por configuração.
    # Modo A (código no notebook): LLM_BASE_URL=http://<ip-da-vpn-do-pc>:11434
    # Modo B (código no PC Windows): LLM_BASE_URL=http://localhost:11434
    LLM_PROVIDER: Literal["ollama", "openai_compatible"] = Field(
        default="ollama",
        description="Provedor do chat model; a fábrica em llm/factory.py escolhe a implementação",
    )
    LLM_BASE_URL: str = Field(default="http://localhost:11434")
    LLM_MODEL: str = Field(default="qwen3:4b-instruct")
    LLM_API_KEY: Optional[SecretStr] = Field(
        default=None, description="Só para APIs externas; o Ollama não usa chave"
    )
    LLM_TEMPERATURE: float = Field(default=0.0, ge=0.0, le=2.0)
    LLM_NUM_CTX: int = Field(
        default=4096, gt=0, description="Janela de contexto do Ollama; consome VRAM (ver D20)"
    )
    LLM_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0)

    def get_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()
