import json
import logging
import hashlib
from typing import Any, Optional
from redis import asyncio as aioredis
from app.core.config import settings

logger = logging.getLogger(__name__)

# Global Redis client
_redis: Optional[aioredis.Redis] = None

async def get_redis() -> Optional[aioredis.Redis]:
    """Returns a singleton async Redis client."""
    global _redis
    if not settings.CACHE_ENABLED:
        return None
    
    if _redis is None:
        try:
            url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}"
            _redis = aioredis.from_url(url, decode_responses=True)
            # Test connection
            await _redis.ping()
            logger.info(f"Connected to Redis at {url}")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Caching will be disabled for this session.")
            _redis = None
    return _redis

def generate_cache_key(prefix: str, *args, **kwargs) -> str:
    """Generates a stable SHA256 hash for a set of arguments."""
    # Serialize args and kwargs to a stable string
    data = {
        "args": args,
        "kwargs": kwargs
    }
    dump = json.dumps(data, sort_keys=True)
    h = hashlib.sha256(dump.encode("utf-8")).hexdigest()
    return f"{prefix}:{h}"

async def get_cached_value(key: str) -> Optional[Any]:
    """Retrieves a value from Redis."""
    redis = await get_redis()
    if not redis:
        return None
    try:
        val = await redis.get(key)
        if val:
            return json.loads(val)
    except Exception as e:
        logger.debug(f"Redis get failed for key {key}: {e}")
    return None

async def set_cached_value(key: str, value: Any, ttl: int = 86400) -> None:
    """Sets a value in Redis with a TTL (default 24h)."""
    redis = await get_redis()
    if not redis:
        return
    try:
        await redis.set(key, json.dumps(value), ex=ttl)
    except Exception as e:
        logger.debug(f"Redis set failed for key {key}: {e}")
