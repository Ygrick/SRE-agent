"""SSE Fix Proxy — patches RMR Responses API stream for Codex CLI compatibility.

RMR sends `response.output_text.delta` without prior `response.output_item.added`
and `response.content_part.added` events. Codex CLI requires these events to track
active items. This proxy injects the missing events.

Runs as a sidecar container, Codex connects to this proxy instead of RMR directly.
"""

import json
import os
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

UPSTREAM_URL = os.getenv("UPSTREAM_URL", "https://rmrrouter.redmadrobot.com").rstrip("/")
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", "")
LISTEN_PORT = int(os.getenv("PORT", "8100"))

app = FastAPI(title="SSE Fix Proxy", version="0.1.0")

_client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def startup() -> None:
    """Initialize httpx client."""
    global _client
    _client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))


@app.on_event("shutdown")
async def shutdown() -> None:
    """Close httpx client."""
    if _client:
        await _client.aclose()


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check."""
    return {"status": "ok"}


async def _patch_sse_stream(
    upstream_response: httpx.Response,
) -> AsyncIterator[bytes]:
    """Read upstream SSE, inject missing events before first delta.

    Injects response.output_item.added and response.content_part.added
    before the first response.output_text.delta for each item_id.

    Args:
        upstream_response: Streaming response from upstream.

    Yields:
        Patched SSE data lines as bytes.
    """
    seen_items: set[str] = set()
    accumulated_text: dict[str, list[str]] = {}  # item_id -> text chunks
    response_created_sent = False

    async for raw_line in upstream_response.aiter_lines():
        if not raw_line.startswith("data: "):
            yield (raw_line + "\n\n").encode()
            continue

        data_str = raw_line[6:]
        if data_str.strip() == "[DONE]":
            yield (raw_line + "\n\n").encode()
            continue

        try:
            event = json.loads(data_str)
        except json.JSONDecodeError:
            yield (raw_line + "\n\n").encode()
            continue

        event_type = event.get("type", "")

        # Inject response.created before any content events
        if event_type == "response.output_text.delta" and not response_created_sent:
            response_created_sent = True
            created_event = {
                "type": "response.created",
                "response": {
                    "id": "resp_proxy",
                    "object": "response",
                    "status": "in_progress",
                    "output": [],
                },
            }
            yield f"data: {json.dumps(created_event)}\n\n".encode()

        # Inject missing events before first delta for each item
        if event_type == "response.output_text.delta":
            item_id = event.get("item_id", "")
            output_index = event.get("output_index", 0)
            content_index = event.get("content_index", 0)

            # Accumulate text
            delta = event.get("delta", "")
            if item_id:
                accumulated_text.setdefault(item_id, []).append(delta)

            if item_id and item_id not in seen_items:
                seen_items.add(item_id)

                # Inject response.output_item.added
                item_added = {
                    "type": "response.output_item.added",
                    "output_index": output_index,
                    "item": {
                        "id": item_id,
                        "type": "message",
                        "role": "assistant",
                        "status": "in_progress",
                        "content": [],
                    },
                }
                yield f"data: {json.dumps(item_added)}\n\n".encode()

                # Inject response.content_part.added
                content_added = {
                    "type": "response.content_part.added",
                    "item_id": item_id,
                    "output_index": output_index,
                    "content_index": content_index,
                    "part": {
                        "type": "output_text",
                        "text": "",
                        "annotations": [],
                    },
                }
                yield f"data: {json.dumps(content_added)}\n\n".encode()

        # Before response.completed, inject done events for tracked items
        if event_type == "response.completed":
            for item_id in seen_items:
                full_text = "".join(accumulated_text.get(item_id, []))
                text_done = {
                    "type": "response.output_text.done",
                    "item_id": item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "text": full_text,
                }
                yield f"data: {json.dumps(text_done)}\n\n".encode()

                item_done = {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "id": item_id,
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": full_text,
                                "annotations": [],
                            }
                        ],
                    },
                }
                yield f"data: {json.dumps(item_done)}\n\n".encode()

        # Pass through original event
        yield (raw_line + "\n\n").encode()


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(path: str, request: Request) -> Response:
    """Proxy all /v1/* requests to upstream, patching SSE streams.

    Args:
        path: URL path after /v1/.
        request: Incoming request.

    Returns:
        Proxied response (streaming if SSE, direct otherwise).
    """
    assert _client is not None

    body = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)

    # Inject upstream API key if not present
    if UPSTREAM_API_KEY and "authorization" not in {k.lower() for k in headers}:
        headers["Authorization"] = f"Bearer {UPSTREAM_API_KEY}"

    url = f"{UPSTREAM_URL}/v1/{path}"

    # Check if streaming request
    is_stream = False
    if body:
        try:
            req_json = json.loads(body)
            is_stream = req_json.get("stream", False)
        except json.JSONDecodeError:
            pass

    if is_stream and path == "responses":
        # Streaming responses — patch SSE
        upstream = await _client.send(
            _client.build_request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
            ),
            stream=True,
        )
        return StreamingResponse(
            _patch_sse_stream(upstream),
            status_code=upstream.status_code,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
    else:
        # Non-streaming — pass through
        resp = await _client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
        )
