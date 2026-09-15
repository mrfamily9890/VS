from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VahanSync Fleet Operations API"
    environment: str = "development"
    database_url: str = "sqlite:///./vahana.db"
    jwt_secret: str = "local-development-secret-change-me"
    access_token_minutes: int = 60
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    seed_admin_email: str = "admin@example.com"
    seed_admin_password: str = "ChangeMe!123"
    storage_path: str = "./storage"
    max_upload_bytes: int = 25 * 1024 * 1024
    storage_backend: str = "local"
    object_storage_bucket: str | None = None
    object_storage_region: str | None = None
    object_storage_endpoint: str | None = None
    identity_provider_issuer: str | None = None
    identity_provider_client_id: str | None = None
    identity_provider_enabled: bool = False
    auth_provider: str = "local"
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_jwt_secret: str | None = None
    supabase_jwks_url: str | None = None
    supabase_storage_bucket: str = "documents"
    sms_provider: str | None = None
    sms_api_url: str | None = None
    sms_auth_token: str | None = None
    sms_sender_id: str | None = None
    sms_template_id: str | None = None
    sms_account_sid: str | None = None
    sms_from_number: str | None = None
    whatsapp_provider: str | None = None
    whatsapp_api_url: str | None = None
    whatsapp_auth_token: str | None = None
    whatsapp_account_sid: str | None = None
    whatsapp_from_number: str | None = None
    whatsapp_sender_id: str | None = None
    whatsapp_template_id: str | None = None
    telematics_default_timeout_seconds: int = 30
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None
    razorpay_plan_starter: str | None = None
    razorpay_plan_growth: str | None = None
    razorpay_plan_scale: str | None = None
    razorpay_plan_enterprise: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_prefix="VAHANA_", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def validate_runtime(self) -> None:
        if self.environment.lower() in {"production", "staging"}:
            if self.jwt_secret == "local-development-secret-change-me":
                raise RuntimeError("VAHANA_JWT_SECRET must be changed outside development")
            if self.seed_admin_password == "ChangeMe!123":
                raise RuntimeError("VAHANA_SEED_ADMIN_PASSWORD must be changed outside development")
        if self.auth_provider == "supabase" and not (self.supabase_jwt_secret or self.supabase_jwks_url):
            raise RuntimeError("Configure VAHANA_SUPABASE_JWT_SECRET or VAHANA_SUPABASE_JWKS_URL when using Supabase Auth")
        if self.storage_backend == "supabase" and not self.supabase_service_role_key:
            raise RuntimeError("VAHANA_SUPABASE_SERVICE_ROLE_KEY is required when VAHANA_STORAGE_BACKEND=supabase")


@lru_cache
def get_settings() -> Settings:
    return Settings()
