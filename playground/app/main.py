"""Playground — тестовый сервис для SRE-агента.

Простое приложение с PostgreSQL и Redis, намеренно имеющее
"слабые места" для демонстрации работы SRE-агента.
"""

import os
import time
from typing import Any

import psycopg2
import redis
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Playground", version="0.1.0")

# --- Connections ---

DB_DSN = os.environ.get(
    "DATABASE_URL",
    "host=playground-postgres dbname=playground user=ai_sre password=changeme-secure-password",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://playground-redis:6379/0")

_redis: redis.Redis | None = None
_pg_conn: psycopg2.extensions.connection | None = None


def get_redis() -> redis.Redis:
    """Get or create Redis connection.

    Returns:
        Active Redis client.
    """
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def get_pg() -> psycopg2.extensions.connection:
    """Get or create PostgreSQL connection.

    Returns:
        Active PostgreSQL connection.
    """
    global _pg_conn
    if _pg_conn is None or _pg_conn.closed:
        _pg_conn = psycopg2.connect(DB_DSN)
        _pg_conn.autocommit = True
        with _pg_conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    payload TEXT,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
    return _pg_conn


# --- Endpoints ---


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check — verifies PostgreSQL and Redis connectivity.

    Returns:
        Status dict with component health.
    """
    status: dict[str, str] = {"status": "ok"}
    try:
        get_pg().cursor().execute("SELECT 1")
        status["postgres"] = "ok"
    except Exception as exc:
        status["postgres"] = f"error: {exc}"
        status["status"] = "degraded"
    try:
        get_redis().ping()
        status["redis"] = "ok"
    except Exception as exc:
        status["redis"] = f"error: {exc}"
        status["status"] = "degraded"
    return status


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint.

    Returns:
        Service info.
    """
    return {"service": "playground", "status": "running"}


@app.get("/api/data")
async def get_data() -> dict[str, Any]:
    """Fetch recent events from PostgreSQL and cache hit count from Redis.

    Returns:
        Dict with events and request counter.
    """
    r = get_redis()
    counter = r.incr("playground:request_count")

    conn = get_pg()
    with conn.cursor() as cur:
        cur.execute("SELECT id, event_type, payload, created_at FROM events ORDER BY id DESC LIMIT 10")
        rows = cur.fetchall()

    return {
        "request_count": counter,
        "events": [
            {"id": row[0], "type": row[1], "payload": row[2], "created_at": str(row[3])}
            for row in rows
        ],
    }


@app.post("/api/events")
async def create_event(event_type: str = "test", payload: str = "") -> dict[str, Any]:
    """Insert a new event into PostgreSQL.

    Args:
        event_type: Event type string.
        payload: Event payload.

    Returns:
        Created event id.
    """
    conn = get_pg()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (event_type, payload) VALUES (%s, %s) RETURNING id",
            (event_type, payload),
        )
        event_id = cur.fetchone()[0]
    return {"id": event_id, "event_type": event_type}


@app.get("/api/cpu-heavy")
async def cpu_heavy(iterations: int = 1_000_000) -> dict[str, Any]:
    """CPU-intensive endpoint for stress testing.

    Args:
        iterations: Number of loop iterations.

    Returns:
        Elapsed time.
    """
    start = time.monotonic()
    total = 0.0
    for i in range(iterations):
        total += i ** 0.5
    elapsed = time.monotonic() - start
    return {"iterations": iterations, "elapsed_seconds": round(elapsed, 3), "result": total}


@app.get("/api/memory-alloc")
async def memory_alloc(mb: int = 10) -> dict[str, str]:
    """Allocate memory for stress testing.

    Args:
        mb: Megabytes to allocate.

    Returns:
        Status with allocated size.

    Raises:
        HTTPException: 400 if mb > 500.
    """
    if mb > 500:
        raise HTTPException(400, "Max 500 MB allowed")
    _data = bytearray(mb * 1024 * 1024)  # noqa: F841
    return {"allocated_mb": str(mb), "status": "ok"}
