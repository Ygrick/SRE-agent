"""MCP Server: qdrant_search — поиск Runbooks в Qdrant.

Stdio-based MCP server для Codex CLI.
Предоставляет tool `qdrant_search` для поиска релевантных Runbooks
по описанию инцидента.

Запуск: python3 -m agent.mcp_servers.qdrant_search_server
Подключение: секция [mcp_servers.qdrant-search] в config.toml
"""

import json
import os
import sys
from typing import Any

# MCP protocol constants
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "runbooks")
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
TOP_K = 3
SCORE_THRESHOLD = 0.5

_model = None
_client = None


def _get_model():
    """Lazy-load embedding model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_client():
    """Lazy-load Qdrant client."""
    global _client
    if _client is None:
        from qdrant_client import QdrantClient
        _client = QdrantClient(url=QDRANT_URL)
    return _client


def search_runbooks(query: str) -> str:
    """Search Qdrant for relevant runbooks.

    Args:
        query: Incident description or keywords.

    Returns:
        Concatenated runbook text or "not found" message.
    """
    model = _get_model()
    client = _get_client()

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


def _respond(request_id: Any, result: dict) -> None:
    """Send JSON-RPC response."""
    msg = {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}
    out = json.dumps(msg)
    sys.stdout.write(f"Content-Length: {len(out.encode())}\r\n\r\n{out}")
    sys.stdout.flush()


def _error(request_id: Any, code: int, message: str) -> None:
    """Send JSON-RPC error."""
    msg = {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": {"code": code, "message": message}}
    out = json.dumps(msg)
    sys.stdout.write(f"Content-Length: {len(out.encode())}\r\n\r\n{out}")
    sys.stdout.flush()


def _handle_request(request: dict) -> None:
    """Handle a single JSON-RPC request."""
    method = request.get("method", "")
    request_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        _respond(request_id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "qdrant-search", "version": "1.0.0"},
        })

    elif method == "notifications/initialized":
        pass  # No response needed for notifications

    elif method == "tools/list":
        _respond(request_id, {
            "tools": [{
                "name": "qdrant_search",
                "description": "Search Runbooks knowledge base for incident diagnostics. "
                    "Use when investigating alerts to find relevant runbooks with "
                    "diagnostic commands and remediation steps.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Incident description or keywords to search for, "
                                "e.g. 'high CPU usage' or 'disk space full'",
                        },
                    },
                    "required": ["query"],
                },
            }],
        })

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "qdrant_search":
            query = arguments.get("query", "")
            try:
                result_text = search_runbooks(query)
                _respond(request_id, {
                    "content": [{"type": "text", "text": result_text}],
                })
            except Exception as exc:
                _respond(request_id, {
                    "content": [{"type": "text", "text": f"Search error: {exc}"}],
                    "isError": True,
                })
        else:
            _error(request_id, -32601, f"Unknown tool: {tool_name}")

    elif method == "ping":
        _respond(request_id, {})

    else:
        if request_id is not None:
            _error(request_id, -32601, f"Method not found: {method}")


def main() -> None:
    """Run MCP server over stdio."""
    buf = ""
    while True:
        # Read headers
        content_length = 0
        while True:
            line = sys.stdin.readline()
            if not line:
                return  # EOF
            line = line.strip()
            if not line:
                break
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())

        if content_length == 0:
            continue

        # Read body
        body = sys.stdin.read(content_length)
        try:
            request = json.loads(body)
            _handle_request(request)
        except json.JSONDecodeError:
            _error(None, -32700, "Parse error")


if __name__ == "__main__":
    main()
