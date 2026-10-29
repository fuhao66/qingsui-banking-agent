from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Banking Agent API"
    app_env: str = "development"
    api_version: str = "0.7.0"
    database_url: str = (
        "postgresql+asyncpg://banking_agent:banking_agent_dev@localhost:5432/banking_agent"
    )
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000"
    security_hmac_secret: str = "local-demo-secret-change-before-deployment"
    demo_otp_code: str = "246810"
    auth_max_failures: int = 3
    auth_lock_minutes: int = 15
    auth_challenge_minutes: int = 3
    public_demo_mode: bool = False
    public_invite_code: str = ""
    admin_api_token: str = ""
    experience_session_hours: int = 8
    experience_max_active_sessions: int = 100
    experience_requests_per_minute: int = 60
    agent_model_provider: Literal["auto", "openai", "qwen", "deterministic"] = "auto"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    dashscope_api_key: str | None = None
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    qwen_vision_model: str = "qwen-vl-plus"
    public_web_base_url: str = "http://localhost:3000"
    channel_link_minutes: int = 10
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_delivery_enabled: bool = False

    @field_validator("qwen_base_url")
    @classmethod
    def validate_qwen_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parsed = urlparse(normalized)
        hostname = parsed.hostname or ""
        if parsed.scheme != "https" or not (
            hostname == "aliyuncs.com" or hostname.endswith(".aliyuncs.com")
        ):
            raise ValueError("QWEN_BASE_URL must use HTTPS on an aliyuncs.com host")
        return normalized

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
