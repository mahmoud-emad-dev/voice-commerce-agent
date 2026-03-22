from __future__ import annotations # Enables postponed evaluation of type hints
from pydantic_settings import BaseSettings , SettingsConfigDict



class Settings(BaseSettings):
        
    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding = "utf-8",
        extra = "ignore",
        case_sensitive = False,
    )

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    gemini_voice_name: str = "Charon"
    
    log_level: str = "INFO"
    app_debug: bool = True
    app_port: int = 8000
    app_version: str = "0.1.0"


settings = Settings()


