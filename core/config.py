from typing import Literal, Optional

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["ollama", "openai_compatible"]
# Papéis de LLM do projeto (D14, D16). Papel desconhecido no .env falha na inicialização.
LLMRoleName = Literal["investigator", "generalist", "judge", "translator"]


class LLMRoleOverride(BaseModel):
    """Sobrescrita opcional por papel; campo ausente herda o valor global `LLM_*`.

    Ex.: `LLM_ROLES__INVESTIGATOR__MODEL=qwen3:8b`, `LLM_ROLES__JUDGE__REASONING=true`.
    """

    provider: Optional[LLMProvider] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[SecretStr] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    num_ctx: Optional[int] = Field(default=None, gt=0)
    reasoning: Optional[bool] = None
    timeout_seconds: Optional[float] = Field(default=None, gt=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
        env_ignore_empty=True,  # LLM_REASONING= ou LLM_API_KEY= vazios contam como não definidos
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
    LLM_PROVIDER: LLMProvider = Field(
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
    LLM_REASONING: Optional[bool] = Field(
        default=None,
        description="Modo de raciocínio (thinking). None = padrão do modelo; false = desligado",
    )
    LLM_ROLES: dict[LLMRoleName, LLMRoleOverride] = Field(
        default_factory=dict, description="Sobrescritas por papel (LLM_ROLES__<PAPEL>__<CAMPO>)"
    )

    def get_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()
