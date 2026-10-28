"""Text -> vector conversion, used both when indexing documents and when searching.

The SAME model must be used for indexing and for querying, so the model follows APP_MODE:

    local  -> text-embedding-3-small (OpenAI, default) or gemini-embedding-001 (LLM_PROVIDER=gemini)
              Switching provider changes the vectors: re-index your documents.
    cloud  -> text-embedding-005 through Vertex AI (Google Cloud credentials)

Both produce 768-dimensional vectors. In cloud mode that number is fixed by the
Vector Search index (see .github/workflows/deploy.yml).

LangChain v1 note: `VertexAIEmbeddings` is deprecated. `GoogleGenerativeAIEmbeddings`
covers both the Gemini API and Vertex AI (vertexai=True), so one class serves both modes.
"""
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from config.settings import settings
from exceptions import ConfigurationError


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    if settings.is_cloud:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        if not settings.GCP_PROJECT:
            raise ConfigurationError("APP_MODE=cloud needs GCP_PROJECT_ID for Vertex AI embeddings.")
        return GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model_name,
            vertexai=True,
            project=settings.GCP_PROJECT,
            location=settings.GCP_REGION,
            output_dimensionality=settings.embedding_dimensions,
        )

    if settings.llm_provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise ConfigurationError("APP_MODE=local with LLM_PROVIDER=openai needs OPENAI_API_KEY in .env for embeddings.")
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=settings.local_embedding_model_name,
            api_key=settings.OPENAI_API_KEY,
            dimensions=settings.embedding_dimensions,
        )

    if not settings.GOOGLE_API_KEY:
        raise ConfigurationError("APP_MODE=local with LLM_PROVIDER=gemini needs GOOGLE_API_KEY in .env for embeddings.")
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(
        model=settings.local_embedding_model_name,
        google_api_key=settings.GOOGLE_API_KEY,
        output_dimensionality=settings.embedding_dimensions,
    )
