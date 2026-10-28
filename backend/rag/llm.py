"""The LLM used by both the RAG chain and the agents.

The provider is chosen with LLM_PROVIDER:
  * openai (default) - OpenAI API, key in OPENAI_API_KEY
  * gemini           - Gemini API, key in GOOGLE_API_KEY
Embeddings (rag/embeddings.py) follow the same provider in local mode; cloud mode uses Vertex AI.
"""
from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from config.settings import settings
from exceptions import ConfigurationError


@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    """Create the chat model on first use (not at import time) and reuse it afterwards."""
    if settings.llm_provider == "gemini":
        if not settings.GOOGLE_API_KEY:
            raise ConfigurationError("GOOGLE_API_KEY is empty. Add it to .env (https://aistudio.google.com/apikey).")
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.llm_model_name,
            google_api_key=settings.GOOGLE_API_KEY,
            temperature=settings.llm_temperature,
        )

    if not settings.OPENAI_API_KEY:
        raise ConfigurationError(
            "OPENAI_API_KEY is empty. Add it to .env (https://platform.openai.com/api-keys), "
            "or set LLM_PROVIDER=gemini."
        )
    from langchain_openai import ChatOpenAI

    kwargs = {}
    if settings.openai_reasoning_effort:
        kwargs["reasoning_effort"] = settings.openai_reasoning_effort
    if settings.openai_temperature is not None:
        kwargs["temperature"] = settings.openai_temperature
    # Reasoning models (gpt-5/6 family) reject tools + reasoning on /v1/chat/completions,
    # so use the Responses API by default. They also reject `temperature`, so it is only sent if set.
    return ChatOpenAI(
        model=settings.llm_model_name,
        api_key=settings.OPENAI_API_KEY,
        use_responses_api=settings.openai_use_responses_api,
        **kwargs,
    )


def extract_text(content) -> str:
    """Models may return a list of content blocks, e.g. [{'type': 'text', 'text': '...'}]; join the text."""
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return content
