# pyrefly: ignore [missing-import]
import logging
from qdrant_client import QdrantClient
from app.core.config import settings

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

async def get_embedding(text: str) -> list[float]:
    """
    Generate embedding using HuggingFace nomic-embed-text model.
    """
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text")

    model = get_embedding_model()
    # sentence-transformers encodes text into a numpy array; convert to float list
    embedding = model.encode(text).tolist()

    if not embedding or len(embedding) == 0:
        raise ValueError("Embedding model returned null or empty vector")

    return embedding
