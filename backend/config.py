"""
config.py – App settings loaded from .env
"""
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/digiprint"
    DEFAULT_STORE: str = "Bondi"
    SECRET_KEY: str = "change-me"
    PAUSE_EMAILS: int = 0

    class Config:
        env_file = Path(__file__).parent / ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()