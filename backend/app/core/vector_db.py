# pyrefly: ignore [missing-import]
import logging
from functools import lru_cache
from qdrant_client import QdrantClient
from app.core.config import settings
from app.core.cache import generate_cache_key, get_cached_value, set_cached_value

logger = logging.getLogger(__name__)

def get_qdrant_client() -> QdrantClient:
    """
    Initialize and return a Qdrant client.
    """
    client = QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT
    )
    return client

def init_qdrant(collection_name: str, vector_size: int = 768):
    """
    Initialize a collection in Qdrant if it doesn't exist.
    nomic-embed-text-v1.5 has a default vector dimension of 768.
    """
    client = get_qdrant_client()
    
    # Check if collection exists
    if not client.collection_exists(collection_name=collection_name):
        from qdrant_client.http.models import Distance, VectorParams
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
    return client

from sentence_transformers import SentenceTransformer

_embedding_model = None

def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True)
    return _embedding_model


def preload_embedding_model() -> None:
    """Eagerly load weights into memory. Call from FastAPI startup so the
    first user upload doesn't pay the 10-30s cold-load cost."""
    get_embedding_model()

from typing import Optional

_EMB_CACHE: dict[str, list[float]] = {}
_MAX_CACHE_SIZE = 2048

def _get_from_cache(text: str) -> Optional[list[float]]:
    """Lookup embedding in the bounded in-memory cache."""
    return _EMB_CACHE.get(text)

def _set_in_cache(text: str, embedding: list[float]) -> None:
    """Insert embedding into the bounded cache with FIFO eviction."""
    if text in _EMB_CACHE:
        _EMB_CACHE.pop(text)
    elif len(_EMB_CACHE) >= _MAX_CACHE_SIZE:
        try:
            # OrderedDict behavior in Python 3.7+: next(iter(dict)) returns the oldest key
            oldest_key = next(iter(_EMB_CACHE))
            _EMB_CACHE.pop(oldest_key)
        except StopIteration:
            pass
    _EMB_CACHE[text] = embedding

def _get_embedding_sync(text: str) -> list[float]:
    """Synchronous cached embedding call."""
    cached = _get_from_cache(text)
    if cached is not None:
        return cached
    model = get_embedding_model()
    embedding = model.encode(text).tolist()
    _set_in_cache(text, embedding)
    return embedding


async def get_embedding(text: str) -> list[float]:
    """
    Generate embedding using HuggingFace nomic-embed-text model.
    Redis + LRU cached to prevent redundant passes for identical blocks.
    """
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text")

    # 1. Check in-process cache first (fastest)
    cached = _get_from_cache(text)
    if cached is not None:
        return cached

    # 2. Check Redis (multi-process / persistent cache)
    cache_key = generate_cache_key("embedding", text=text)
    cached_res = await get_cached_value(cache_key)
    if cached_res:
        _set_in_cache(text, cached_res)
        return cached_res

    # 3. Compute if not in Redis
    embedding = _get_embedding_sync(text)

    if not embedding or len(embedding) == 0:
        raise ValueError("Embedding model returned null or empty vector")

    # 4. Save to Redis (30 day TTL - embeddings are deterministic)
    await set_cached_value(cache_key, embedding, ttl=2592000)

    return embedding


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for a list of texts.
    Deduplicates, looks up in _EMB_CACHE and Redis, runs one batched encode for misses,
    stores results in the caches, and returns the embeddings in the input order.
    """
    if not texts:
        return []

    import asyncio

    # Filter out empty or whitespace texts (matching single path validation)
    for t in texts:
        if not t or not t.strip():
            raise ValueError("Cannot embed empty text")

    # Deduplicate unique texts
    unique_texts = list(set(texts))
    embeddings_map = {}

    # 1. Look up in _EMB_CACHE first
    misses_after_in_proc = []
    for text in unique_texts:
        cached = _get_from_cache(text)
        if cached is not None:
            embeddings_map[text] = cached
        else:
            misses_after_in_proc.append(text)

    # 2. Check Redis for any remaining misses
    if misses_after_in_proc:
        redis_keys = [generate_cache_key("embedding", text=t) for t in misses_after_in_proc]
        redis_results = await asyncio.gather(*(get_cached_value(k) for k in redis_keys), return_exceptions=True)

        redis_misses = []
        for text, result in zip(misses_after_in_proc, redis_results):
            if result and isinstance(result, list):
                embeddings_map[text] = result
                _set_in_cache(text, result)
            else:
                redis_misses.append(text)
    else:
        redis_misses = []

    # 3. Batch encode remaining misses on CPU
    if redis_misses:
        model = get_embedding_model()
        # Single vectorized model.encode pass
        encoded_embeddings = model.encode(redis_misses).tolist()

        redis_sets = []
        for text, embedding in zip(redis_misses, encoded_embeddings):
            if not embedding or len(embedding) == 0:
                raise ValueError("Embedding model returned null or empty vector")

            embeddings_map[text] = embedding
            _set_in_cache(text, embedding)

            cache_key = generate_cache_key("embedding", text=text)
            redis_sets.append(set_cached_value(cache_key, embedding, ttl=2592000))

        if redis_sets:
            await asyncio.gather(*redis_sets, return_exceptions=True)

    # Reassemble and return results in the input order
    return [embeddings_map[t] for t in texts]

