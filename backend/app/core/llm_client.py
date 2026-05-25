"""LLM client abstraction: unified Groq/OpenAI interface."""
import logging
from groq import AsyncGroq
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.cache import generate_cache_key, get_cached_value, set_cached_value

logger = logging.getLogger(__name__)


def get_llm_client():
    """Returns appropriate LLM client (Groq or OpenAI) based on config."""
    if settings.LLM_PROVIDER.lower() == "groq":
        return AsyncGroq(api_key=settings.GROQ_API_KEY)
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def get_model_name() -> str:
    """Default model — fast tier for bulk work."""
    if settings.LLM_PROVIDER.lower() == "groq":
        return settings.GROQ_MODEL_FAST
    return "gpt-4o"


def get_smart_model() -> str:
    """Stronger model for obedience-critical calls (routing, refusals, answers)."""
    if settings.LLM_PROVIDER.lower() == "groq":
        return settings.GROQ_MODEL_SMART
    return "gpt-4o"


async def _chat(messages: list, json_mode: bool = False, use_cache: bool = True,
                model: str | None = None) -> str:
    """Unified chat completion call with Redis caching.

    Set use_cache=False for interactive/chat calls where re-asking the same
    prompt should produce a fresh answer (e.g. "give me another version").
    Pass `model` to override the default (e.g. get_smart_model() for routing).
    """
    model = model or get_model_name()

    # Check cache
    cache_key = None
    if use_cache:
        cache_key = generate_cache_key("llm_chat", messages=messages, json_mode=json_mode, model=model)
        cached_res = await get_cached_value(cache_key)
        if cached_res:
            logger.debug(f"Cache hit for LLM chat: {cache_key[:15]}...")
            return cached_res

    client = get_llm_client()

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

    # Save to cache (24h TTL)
    if use_cache and cache_key is not None:
        await set_cached_value(cache_key, content, ttl=86400)

    return content
