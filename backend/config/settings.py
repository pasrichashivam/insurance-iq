"""All configuration in one place, read from environment variables / .env.

THE LOCAL <-> CLOUD TOGGLE
--------------------------
    APP_MODE=local   (default)  Runs on your laptop. Vectors -> Chroma (./.insurance_iq/chroma),
                                Files -> ./.insurance_iq/uploads. No Google Cloud project needed.

    APP_MODE=cloud              Runs against Google Cloud (what Cloud Run uses).
                                Vectors  -> Vertex AI Vector Search
                                Files    -> Cloud Storage bucket

    LLM_PROVIDER / EMBEDDING_PROVIDER = openai | google are independent of APP_MODE and of each other
    (EMBEDDING_PROVIDER defaults to LLM_PROVIDER). Google in cloud mode goes through Vertex AI
    (Google Cloud credentials); in local mode through the Gemini API (GOOGLE_API_KEY).

Every module that touches storage asks `settings.is_cloud` instead of guessing,
so switching mode is one line in .env.
"""
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = two levels above backend/config/
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # --- App ---
    app_name: str = "Insurance-IQ"
    app_env: str = Field("local", validation_alias="ENVIRONMENT")
    app_version: str = "2.0.0"

    insurance_db_path: str = Field(
        str(PROJECT_ROOT / "backend" / "data" / "cardinal_ridge.db"), validation_alias="INSURANCE_DB_PATH"
    )

    app_mode: Literal["local", "cloud"] = Field("local", validation_alias="APP_MODE")

    llm_provider: Literal["openai", "google"] = Field("", validation_alias="LLM_PROVIDER")
    embedding_provider: Literal["openai", "google", ""] = Field("", validation_alias="EMBEDDING_PROVIDER")
    
    OPENAI_API_KEY: str = Field("", validation_alias="OPENAI_API_KEY")
    # Responses API works with tools for reasoning models; set false for plain chat-completions models
    openai_use_responses_api: bool = Field(True, validation_alias="OPENAI_USE_RESPONSES_API")
    
    GOOGLE_API_KEY: str = Field("", validation_alias="GOOGLE_API_KEY")
    
    # openai -> gpt-6.1-sol, google -> gemini-3.8-flash
    llm_model_name: str = Field("", validation_alias="LLM_MODEL_NAME")

    # --- Embeddings ---
    # google -> text-embedding-005 (cloud / Vertex AI)
    embedding_model_name: str = Field("", validation_alias="EMBEDDING_MODEL_NAME")
    
    # Empty = 768 for google, 1536 for openai
    embedding_dimensions: int | None = Field(None, validation_alias="EMBEDDING_DIMENSIONS")
    
    llm_temperature: float = Field(0.0, validation_alias="LLM_TEMPERATURE")

    # --- Local mode storage ---
    local_data_dir: str = Field(str(PROJECT_ROOT / ".insurance_iq"), validation_alias="LOCAL_DATA_DIR")
    chroma_collection: str = Field("insurance_docs", validation_alias="CHROMA_COLLECTION")

    # --- Cloud mode (GCP) ---
    GCP_PROJECT: str = Field("", validation_alias="GCP_PROJECT_ID")
    GCP_REGION: str = Field("us-central1", validation_alias="GCP_REGION")
    GCS_BUCKET_NAME: str = Field("", validation_alias="GCS_BUCKET_NAME")
    GCS_PREFIX: str = Field("uploads/", validation_alias="GCS_PREFIX")
    gcp_service_account_path: str = Field("", validation_alias="GCP_SERVICE_ACCOUNT_PATH")
    vector_search_index_id: str = Field("", validation_alias="VECTOR_SEARCH_INDEX_ID")
    vector_search_index_endpoint_id: str = Field("", validation_alias="VECTOR_SEARCH_INDEX_ENDPOINT_ID")

    # --- Agent middleware limits ---
    agent_max_model_calls: int = Field(8, validation_alias="AGENT_MAX_MODEL_CALLS")
    agent_max_tool_calls: int = Field(6, validation_alias="AGENT_MAX_TOOL_CALLS")
    agent_max_retries: int = Field(2, validation_alias="AGENT_MAX_RETRIES")

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),  # found no matter which folder you start from
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # `LLM_MODEL_NAME=` in .env means "use the default"
        extra="ignore",
    )

    @model_validator(mode="after")
    def _normalise(self) -> "Settings":
        # Vertex AI Vector Search expects the prefix to end with "/"
        if self.GCS_PREFIX and not self.GCS_PREFIX.endswith("/"):
            self.GCS_PREFIX += "/"
        if not self.llm_model_name:
            self.llm_model_name = "gemini-3.8-flash" if self.llm_provider == "google" else "gpt-6.1-sol"
        if not self.embedding_model_name:
            self.embedding_model_name = "text-embedding-005" if self.embedding_provider == "google" else "text-embedding-3-small"
        if not self.embedding_dimensions:
            self.embedding_dimensions = 1536 if self.embedding_provider == "openai" else 768
        return self

    # --- Convenience ---
    @property
    def is_cloud(self) -> bool:
        return self.app_mode == "cloud"

    @property
    def chroma_dir(self) -> str:
        return os.path.join(self.local_data_dir, "chroma")

    @property
    def local_upload_dir(self) -> str:
        return os.path.join(self.local_data_dir, "uploads")

    def missing_cloud_settings(self) -> list[str]:
        """Names of cloud settings that are still empty (used for clear error messages)."""
        required = {
            "GCP_PROJECT_ID": self.GCP_PROJECT,
            "GCS_BUCKET_NAME": self.GCS_BUCKET_NAME,
            "VECTOR_SEARCH_INDEX_ID": self.vector_search_index_id,
            "VECTOR_SEARCH_INDEX_ENDPOINT_ID": self.vector_search_index_endpoint_id,
        }
        return [name for name, value in required.items() if not value]

settings = Settings()

# Cloud mode on a laptop: point Google's client libraries at the service-account key.
# (On Cloud Run nothing is set here; the service's own identity is used.)
if settings.is_cloud and settings.gcp_service_account_path:
    key_path = Path(settings.gcp_service_account_path)
    if not key_path.is_absolute():
        key_path = PROJECT_ROOT / key_path
    if key_path.exists():
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(key_path))
