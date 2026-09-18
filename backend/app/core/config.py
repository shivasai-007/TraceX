"""
Central configuration for TraceX.

Everything is read from environment variables (via .env in development),
with safe defaults so the app can start on a bare checkout before any
external service is configured. See backend/.env.example for the full,
documented list of settings.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Core ---
    app_name: str = "TraceX"
    environment: str = "development"
    secret_key: str = "insecure-dev-key-change-me"
    access_token_expire_minutes: int = 480
    log_level: str = "INFO"

    # --- Database ---
    database_url: str = "sqlite:///./tracex.db"

    # --- Graph store ---
    graph_backend: str = "networkx"  # "networkx" | "neo4j"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # --- Queue / cache ---
    redis_url: str = ""  # empty => synchronous pipeline, no Celery required

    # --- Blockchain providers ---
    etherscan_api_key: str = ""
    bitcoin_api_base_url: str = "https://blockstream.info/api"

    # --- ML ---
    risk_model_path: str = "../ml/models/wallet_risk_baseline.joblib"

    # --- AI Copilot ---
    anthropic_api_key: str = ""
    copilot_model: str = "claude-sonnet-4-6"

    # --- CORS ---
    frontend_origin: str = "http://localhost:5173"

    @property
    def workers_enabled(self) -> bool:
        return bool(self.redis_url)

    @property
    def copilot_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
