from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./billproof.db"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    max_upload_mb: int = 10
    max_pdf_pages: int = 20
    case_ttl_hours: int = 24
    demo_mode: bool = True
    log_level: str = "INFO"

    external_pdf_extraction_enabled: bool = False
    anthropic_api_key: str = ""
    anthropic_model: str = ""

    mcp_transport: str = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8001

    cms_provider_dataset_id: str = "xubh-q36u"
    cms_inpatient_dataset_uuid: str = ""
    cms_outpatient_dataset_uuid: str = ""

    turquoise_enabled: bool = False
    turquoise_client_id: str = ""
    turquoise_client_secret: str = ""
    turquoise_organization_id: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
