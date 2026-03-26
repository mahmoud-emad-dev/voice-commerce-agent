from __future__ import annotations # Enables postponed evaluation of type hints
from pydantic_settings import BaseSettings , SettingsConfigDict



class Settings(BaseSettings):

    # -------------------------------------------------------------------------
    # pydantic-settings model configuration
    # -------------------------------------------------------------------------
    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding = "utf-8",
        extra = "ignore",
        case_sensitive = False,
    )

    # =========================================================================
    # PHASE 2+ — Gemini AI Configuration
    # =========================================================================
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    gemini_voice_name: str = "Charon"

    
    # =========================================================================
    # APPLICATION SETTINGS
    # =========================================================================
    log_level: str = "INFO"
    app_debug: bool = True
    app_port: int = 8000
    app_version: str = "0.1.0"
    # Which domains can make requests to this API. In production, set this to frontend's real domain name.
    cors_allow_origins: list[str] = ["*"]


# THE SINGLETON INSTANCE
settings = Settings()


