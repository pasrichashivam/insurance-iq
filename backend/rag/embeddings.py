"""Text -> vector conversion, used both when indexing documents and when searching.

The provider is chosen with EMBEDDING_PROVIDER (defaults to LLM_PROVIDER), independent of APP_MODE:

    openai -> text-embedding-3-small (OPENAI_API_KEY)
    google -> text-embedding-005 on Vertex AI when APP_MODE=cloud (Google Cloud credentials),
    on the Gemini API when APP_MODE=local (GOOGLE_API_KEY)

All vectors are EMBEDDING_DIMENSIONS long: 768 for google, 1536 for openai (unless overridden).
The Vertex AI Vector Search index is created with 768 (see .github/workflows/deploy.yml), so use
EMBEDDING_PROVIDER=google in cloud mode, or recreate the index with 1536 dimensions for openai.
"""
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from config.settings import settings
from exceptions import ConfigurationError


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    if settings.embedding_provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise ConfigurationError("EMBEDDING_PROVIDER=openai needs OPENAI_API_KEY in .env.")
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=settings.embedding_model_name,
            api_key=settings.OPENAI_API_KEY,
            dimensions=settings.embedding_dimensions,
        )

    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    if settings.is_cloud:
        if not settings.GCP_PROJECT:
            raise ConfigurationError("APP_MODE=cloud with EMBEDDING_PROVIDER=google needs GCP_PROJECT_ID.")
        return GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model_name,
            vertexai=True,
            project=settings.GCP_PROJECT,
            location=settings.GCP_REGION,
            output_dimensionality=settings.embedding_dimensions,
        )

    if not settings.GOOGLE_API_KEY:
        raise ConfigurationError("EMBEDDING_PROVIDER=google needs GOOGLE_API_KEY in .env.")
    return GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model_name,
        google_api_key=settings.GOOGLE_API_KEY,
        output_dimensionality=settings.embedding_dimensions,
    )
