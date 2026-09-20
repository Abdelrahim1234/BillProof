from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    allow_real_phi: bool = False
    store_raw_documents: bool = False

    # The local JSON store remains the explicit default for development and
    # tests. Merely defining MONGODB_URI must never redirect an application or
    # admin command to Atlas; STORAGE_BACKEND=mongodb is required as well.
    storage_backend: Literal["file", "mongodb"] = "file"
    private_db_name: str = "billproof_private"
    public_db_name: str = "billproof_public"

    # MongoDB settings are backend-only. SecretStr prevents an accidental
    # Settings repr/trace from exposing credentials. A remote host requires a
    # second, deliberate opt-in in addition to STORAGE_BACKEND=mongodb.
    mongodb_uri: SecretStr | None = None
    mongodb_private_database: str = "billproof_private"
    mongodb_public_database: str = "billproof_public"
    mongodb_allow_remote: bool = False
    mongodb_server_selection_timeout_ms: int = 5000
    mongodb_cleanup_writes_enabled: bool = False

    case_token_secret: str = ""
    hmac_identifier_key: str = ""

    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    max_upload_mb: int = 15
    max_pdf_pages: int = 20
    case_ttl_hours: int = 24
    original_retention_hours: int = 24
    case_retention_days: int = 30
    chat_retention_hours: int = 24
    demo_mode: bool = True
    log_level: str = "INFO"

    ocr_provider: str = "local"
    explanation_provider: str = "deterministic"
    explanation_model: str = ""

    external_pdf_extraction_enabled: bool = False
    anthropic_api_key: str = ""
    anthropic_model: str = ""

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"

    azure_document_intelligence_endpoint: str = ""
    azure_document_intelligence_key: str = ""
    llm_api_key: str = ""
    object_store_bucket: str = ""
    object_store_region: str = ""
    kms_key_id: str = ""

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

    # CLAUDE_FINAL_DEMO_HARDENING_PROMPT Section 0 (scope lock). Other
    # facilities (e.g. Inova, seeded in an earlier session) may remain
    # stored -- they are just excluded from the active demo market, never
    # deleted. Read via active_market_facility_list, never split ad hoc.
    active_market_id: str = "nrv_core_v1"
    active_market_facilities: str = "LewisGale Hospital Montgomery,Carilion New River Valley Medical Center"

    @property
    def active_market_facility_list(self) -> list[str]:
        return [f.strip() for f in self.active_market_facilities.split(",") if f.strip()]

    inova_source_host: str = "www.inova.org"
    inova_mrf_url: str = (
        "https://www.inova.org/sites/default/files/patient_visitor/price_transparency/"
        "2026/540620889_inova-fairfax-hospital_standardcharges.csv"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
