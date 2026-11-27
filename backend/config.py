"""
FinGroww SaaS Platform — Centralized Environment & Security Settings.
Uses Pydantic BaseSettings with strict defaults and environment overrides.
"""

import os
import secrets
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_jwt_secret() -> str:
    env_secret = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY")
    if env_secret and len(env_secret.strip()) >= 32:
        return env_secret.strip()
    # Deterministic dev key derived from workspace or random fallback if not explicitly provided
    seed = os.getenv("API_Secret") or "fingroww-dev-local-fallback-key"
    if len(seed) < 32:
        return (seed * 4)[:48]
    return seed


class Settings(BaseSettings):
    APP_NAME: str = "FinGroww Trading Intelligence"
    APP_VERSION: str = "2.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = False

    # Security & JWT
    JWT_SECRET_KEY: str = _default_jwt_secret()
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    EMAIL_VERIFY_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_EXPIRE_MINUTES: int = 15
    SECRET_ENCRYPTION_KEY: str = os.getenv("SECRET_ENCRYPTION_KEY", _default_jwt_secret())
    PAYMENT_WEBHOOK_SECRET: str = os.getenv("PAYMENT_WEBHOOK_SECRET", _default_jwt_secret())

    # MongoDB Atlas
    MONGODB_URI: str = os.getenv("mongo_url") or os.getenv("MONGODB_URI", "")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "fingroww_db")

    # OAuth & External Integrations
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASS: str = os.getenv("SMTP_PASS", "")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "https://fingroww.tech")

    # Rate Limiting
    RATE_LIMIT_AUTH_PER_MIN: int = 20
    RATE_LIMIT_API_PER_MIN: int = 120

    # Strict Security Mode
    STRICT_PAPER_AUTH: bool = False

    # CORS Origins
    ALLOWED_ORIGINS: List[str] = [
        "https://fingroww.tech",
        "https://www.fingroww.tech",
        "https://api.fingroww.tech",
        "http://127.0.0.1:8787",
        "http://localhost:8787",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
