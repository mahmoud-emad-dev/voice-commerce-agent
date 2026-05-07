from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings loaded from environment variables."""

    # -------------------------------------------------------------------------
    # pydantic-settings model configuration
    # -------------------------------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # =========================================================================
    #  Gemini AI Configuration
    # =========================================================================
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    # gemini_voice_name: str = "Charon"
    gemini_voice_name: str = "Puck"

    @property
    def is_gemini_configured(self) -> bool:
        """True when the Gemini API key is available."""
        return bool(self.gemini_api_key)

    # =========================================================================
    # APPLICATION SETTINGS
    # =========================================================================
    log_level: str = "INFO"
    app_debug: bool = True
    app_port: int = 8000
    app_version: str = "0.1.0"
    debug_payload_logs: bool = False
    enable_public_demo: bool | None = None
    # Which domains can make requests to this API. In production, replace the
    # demo wildcard with the real frontend origin.
    cors_allow_origins: list[str] = ["*"]
    admin_api_key: str = "dev-admin-key"

    @property
    def is_public_demo_enabled(self) -> bool:
        """
        Enable the demo page automatically in local debug mode unless explicitly overridden.
        Safe default for public deployments remains off when APP_DEBUG is false.
        """
        if self.enable_public_demo is not None:
            return self.enable_public_demo
        return self.app_debug

    # =========================================================================
    # STORE SETTINGS
    # ========================================================================
    store_name: str = "NEXFIT"
    assistant_name: str = "PHOENIX"
    store_tagline: str = "Your go-to store for performance sports gear."

    # =========================================================================
    # WooCommerce SETTINGS
    # =========================================================================
    wc_store_url: str = ""
    wc_consumer_key: str = ""
    wc_consumer_secret: str = ""
    wc_timeout: int = 30
    wc_verify_ssl: bool = True

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
        """Base WooCommerce REST API URL derived from the configured store URL."""
        return f"{self.wc_store_url.rstrip('/')}/wp-json/wc/v3"

    # =========================================================================
    # RAG / Vector Search SETTINGS
    # =========================================================================
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dimension: int = 384
    qdrant_collection: str = "products"
    qdrant_mode: str = "memory"
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    @property
    def qdrant_uses_server(self) -> bool:
        """True when Qdrant should be reached over the network instead of in-memory."""
        return self.qdrant_mode.strip().lower() == "server"

    # =========================================================================
    # SESSION STATE / POSTGRES SETTINGS
    # =========================================================================
    postgres_enabled: bool = False
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "voice_commerce"
    postgres_user: str = "voice_commerce"
    postgres_password: str = "voice_commerce"

    @property
    def postgres_dsn(self) -> str:
        """Build the PostgreSQL DSN used by the session-state store."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # =========================================================================
    # TENANT SETTINGS
    # =========================================================================
    tenant_mode: str = "demo"
    demo_tenant_id: str = "demo"
    demo_tenant_name: str = "NEXFIT Demo"
    demo_tenant_api_key: str = "demo-local-key"
    demo_tenant_allowed_origins: list[str] = ["*"]
    demo_tenant_catalog_path: str = "tests/products.csv"


settings = Settings()
