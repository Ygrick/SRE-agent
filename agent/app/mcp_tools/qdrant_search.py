"""MCP Tool: qdrant_search — поиск релевантных Runbooks.

Используется Codex через MCP для поиска инструкций по диагностике инцидентов.
"""

import os

from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "runbooks")
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
TOP_K = 3
SCORE_THRESHOLD = 0.7

_model: SentenceTransformer | None = None
_client: QdrantClient | None = None


def _get_model() -> SentenceTransformer:
    """Lazy-load the embedding model.

    Returns:
        SentenceTransformer instance.
    """
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_client() -> QdrantClient:
    """Lazy-load the Qdrant client.

    Returns:
        QdrantClient instance.
    """
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL)
    return _client


def search(query: str) -> str:
    """Search Runbooks by incident description.

    Embeds the query with intfloat/multilingual-e5-small,
    performs cosine similarity search in Qdrant,
    and returns concatenated text of top-K relevant chunks.

    Args:
        query: Incident description or keywords.

    Returns:
        Concatenated text of relevant Runbook sections,
        or a message if nothing found.
    """
    model = _get_model()
    client = _get_client()

    # e5 models require "query: " prefix for queries
    embedding = model.encode(f"query: {query}", normalize_embeddings=True).tolist()

    response = client.query_points(
        collection_name=COLLECTION,
        query=embedding,
        limit=TOP_K,
        score_threshold=SCORE_THRESHOLD,
    )

    if not response.points:
        return "No relevant runbooks found for this incident."

    parts: list[str] = []
    for hit in response.points:
        payload = hit.payload or {}
        source = payload.get("source_file", "unknown")
        section = payload.get("section_title", "")
        text = payload.get("text", "")
        parts.append(f"--- {source} > {section} (score: {hit.score:.2f}) ---\n{text}")

    return "\n\n".join(parts)
