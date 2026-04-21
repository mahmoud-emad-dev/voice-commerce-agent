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
    #  Gemini AI Configuration
    # =========================================================================
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    gemini_voice_name: str = "Charon"
    
    @property
    def is_gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)
    
    # =========================================================================
    # APPLICATION SETTINGS
    # =========================================================================
    log_level: str = "INFO"
    app_debug: bool = True
    app_port: int = 8000
    app_version: str = "0.1.0"
    # Which domains can make requests to this API. In production, set this to frontend's real domain name.
    cors_allow_origins: list[str] = ["*"]

    # =========================================================================
    # STORE SETTINGS
    # ========================================================================
    store_name: str = "NEXFIT"
    assistant_name:  str = "PHOENIX"
    store_tagline:   str = "Your go-to store for performance sports gear."

    # =========================================================================
    # WooCommerce SETTINGS
    # =========================================================================
    wc_store_url:       str = ""
    wc_consumer_key:    str = ""
    wc_consumer_secret: str = ""    
    wc_timeout:         int = 30
    
    # ── Computed properties ───────────────────────────────────────────────────
    @property
    def is_woocommerce_configured(self) -> bool:
        """
        True when all three WooCommerce credentials are set.
        Used in lifespan (skip WC init if not configured) and in
        product_tools (fall back to empty results if not configured).
        """
        return bool(self.wc_store_url and self.wc_consumer_key and self.wc_consumer_secret)

    @property
    def woocommerce_api_url(self) -> str:
        return f"{self.wc_store_url.rstrip('/')}/wp-json/wc/v3"

    # =========================================================================
    # RAG / Vector Search SETTINGS
    # =========================================================================
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dimension: int = 384
    qdrant_collection: str = "products"

# THE SINGLETON INSTANCE
settings = Settings()


