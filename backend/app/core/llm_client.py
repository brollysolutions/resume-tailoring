"""LLM client abstraction: unified Groq/OpenAI interface."""
import logging
from groq import AsyncGroq
from openai import AsyncOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)


def get_llm_client():
    """Returns appropriate LLM client (Groq or OpenAI) based on config."""
    if settings.LLM_PROVIDER.lower() == "groq":
        return AsyncGroq(api_key=settings.GROQ_API_KEY)
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def get_model_name() -> str:
    """Returns model name for current provider."""
    if settings.LLM_PROVIDER.lower() == "groq":
        return "llama-3.1-8b-instant"
    return "gpt-4o"


async def _chat(messages: list, json_mode: bool = False) -> str:
    """Unified chat completion call.

    Args:
        messages: OpenAI-format message list
        json_mode: If True, request JSON output format

    Returns:
        Response content string

    Raises:
        ValueError: If LLM returns no content
    """
    client = get_llm_client()
    model = get_model_name()

    kwargs = {
        "messages": messages,
        "model": model,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = await client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    if content is None:
        raise ValueError("LLM returned no content (possible refusal or tool-only response)")
    return content
