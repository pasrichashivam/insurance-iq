"""The LLM used by both the RAG chain and the agents.

The provider is chosen with LLM_PROVIDER:
  * openai (default) - OpenAI API, key in OPENAI_API_KEY
  * google           - Gemini: API key in GOOGLE_API_KEY
Embeddings are configured separately with EMBEDDING_PROVIDER (rag/embeddings.py).
"""
from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from config.settings import settings
from exceptions import ConfigurationError


@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    """Create the chat model on first use (not at import time) and reuse it afterwards."""
    if settings.llm_provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        if settings.is_cloud:
            if not settings.GCP_PROJECT:
                raise ConfigurationError("APP_MODE=cloud with LLM_PROVIDER=google needs GCP_PROJECT_ID.")
            return ChatGoogleGenerativeAI(
                model=settings.llm_model_name,
                vertexai=True,
                project=settings.GCP_PROJECT,
                location=settings.GCP_REGION,
                temperature=settings.llm_temperature,
            )
        if not settings.GOOGLE_API_KEY:
            raise ConfigurationError("GOOGLE_API_KEY is empty. Add it to .env (https://aistudio.google.com/apikey).")
        return ChatGoogleGenerativeAI(
            model=settings.llm_model_name,
            google_api_key=settings.GOOGLE_API_KEY,
            temperature=settings.llm_temperature,
        )

    if not settings.OPENAI_API_KEY:
        raise ConfigurationError(
            "OPENAI_API_KEY is empty. Add it to .env (https://platform.openai.com/api-keys), "
            "or set LLM_PROVIDER=google."
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.llm_model_name,
        api_key=settings.OPENAI_API_KEY,
        use_responses_api=settings.openai_use_responses_api
    )


def extract_text(content) -> str:
    """Models may return a list of content blocks, e.g. [{'type': 'text', 'text': '...'}]; join the text."""
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return content
