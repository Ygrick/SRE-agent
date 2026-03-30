"""Index Runbooks into Qdrant vector database.

Parses .md files from runbooks/ directory, splits by H1/H2 headings,
generates embeddings via intfloat/multilingual-e5-small,
and upserts into Qdrant collection.

Usage:
    uv run python scripts/index_runbooks.py [--runbooks-dir /path/to/runbooks]
"""

import hashlib
import re
import sys
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

# --- Config ---

QDRANT_URL = "http://localhost:6333"
COLLECTION = "runbooks"
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
VECTOR_SIZE = 384
CHUNK_MAX_TOKENS = 512  # approximate, 1 token ≈ 4 chars
CHUNK_OVERLAP_CHARS = 256  # ~64 tokens


def split_by_headings(text: str, source_file: str) -> list[dict[str, str]]:
    """Split markdown text by H1/H2 headings into semantic chunks.

    Args:
        text: Full markdown content.
        source_file: Source filename for metadata.

    Returns:
        List of chunk dicts with 'text', 'source_file', 'section_title'.
    """
    sections: list[dict[str, str]] = []
    current_title = source_file
    current_lines: list[str] = []

    for line in text.splitlines():
        if re.match(r"^#{1,2}\s+", line):
            if current_lines:
                body = "\n".join(current_lines).strip()
                if body:
                    sections.append({
                        "text": f"# {current_title}\n\n{body}",
                        "source_file": source_file,
                        "section_title": current_title,
                    })
            current_title = re.sub(r"^#+\s+", "", line).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append({
                "text": f"# {current_title}\n\n{body}",
                "source_file": source_file,
                "section_title": current_title,
            })

    return sections


def further_split(chunk: dict[str, str], max_chars: int = CHUNK_MAX_TOKENS * 4) -> list[dict[str, str]]:
    """Split a chunk further if it exceeds max_chars.

    Args:
        chunk: Chunk dict with 'text', 'source_file', 'section_title'.
        max_chars: Maximum character length per chunk.

    Returns:
        List of chunks (may be the original if small enough).
    """
    text = chunk["text"]
    if len(text) <= max_chars:
        return [chunk]

    parts: list[dict[str, str]] = []
    start = 0
    idx = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        parts.append({
            "text": text[start:end],
            "source_file": chunk["source_file"],
            "section_title": f"{chunk['section_title']} (part {idx})",
        })
        start = end - CHUNK_OVERLAP_CHARS
        idx += 1
    return parts


def chunk_id(source_file: str, section_title: str) -> str:
    """Generate deterministic ID for a chunk.

    Args:
        source_file: Source filename.
        section_title: Section heading.

    Returns:
        Hex string ID.
    """
    key = f"{source_file}::{section_title}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def main(runbooks_dir: str = "runbooks") -> None:
    """Index all runbooks into Qdrant.

    Args:
        runbooks_dir: Directory containing .md runbook files.
    """
    runbooks_path = Path(runbooks_dir)
    if not runbooks_path.exists():
        print(f"Error: directory {runbooks_dir} not found")
        sys.exit(1)

    md_files = sorted(runbooks_path.glob("*.md"))
    if not md_files:
        print(f"No .md files found in {runbooks_dir}")
        sys.exit(1)

    print(f"Found {len(md_files)} runbook files")

    # Parse and chunk
    all_chunks: list[dict[str, str]] = []
    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        sections = split_by_headings(text, md_file.name)
        for section in sections:
            all_chunks.extend(further_split(section))

    print(f"Total chunks: {len(all_chunks)}")

    # Load embedding model
    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)

    # Generate embeddings (e5 models need "query: " or "passage: " prefix)
    texts_for_embedding = [f"passage: {c['text']}" for c in all_chunks]
    print("Generating embeddings...")
    embeddings = model.encode(texts_for_embedding, show_progress_bar=True, normalize_embeddings=True)

    # Connect to Qdrant
    client = QdrantClient(url=QDRANT_URL)

    # Recreate collection
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
        print(f"Deleted existing collection '{COLLECTION}'")

    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )
    print(f"Created collection '{COLLECTION}' ({VECTOR_SIZE}d cosine)")

    # Upsert points
    points = [
        PointStruct(
            id=chunk_id(chunk["source_file"], chunk["section_title"]),
            vector=embedding.tolist(),
            payload={
                "text": chunk["text"],
                "source_file": chunk["source_file"],
                "section_title": chunk["section_title"],
            },
        )
        for chunk, embedding in zip(all_chunks, embeddings)
    ]

    client.upsert(collection_name=COLLECTION, points=points)
    print(f"Indexed {len(points)} chunks into Qdrant")

    # Verify
    info = client.get_collection(COLLECTION)
    print(f"Collection '{COLLECTION}': {info.points_count} points")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Index runbooks into Qdrant")
    parser.add_argument("--runbooks-dir", default="runbooks", help="Path to runbooks directory")
    args = parser.parse_args()
    main(args.runbooks_dir)
