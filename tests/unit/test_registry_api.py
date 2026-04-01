"""Tests for registry.app.main: FastAPI endpoints.

Uses dependency overrides to avoid real PostgreSQL.
We test the well-known endpoint (no auth) and mock the DB-dependent endpoints.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from fastapi.testclient import TestClient


@pytest.fixture()
def registry_client() -> TestClient:
    """Create a TestClient for the registry app with overridden dependencies.

    Overrides verify_api_key and get_session to avoid real DB/auth.
    """
    # Must set env vars before importing registry config (which reads them at import time)
    import os

    os.environ.setdefault("REGISTRY_DATABASE_URL", "sqlite+aiosqlite:///test.db")
    os.environ.setdefault("REGISTRY_API_KEY", "test-api-key")

    from registry.app.main import app, verify_api_key

    # Override auth to always pass
    async def _noop_auth() -> None:
        return None

    app.dependency_overrides[verify_api_key] = _noop_auth

    return TestClient(app, raise_server_exceptions=False)


class TestWellKnownEndpoint:
    """Tests for GET /.well-known/agent-card.json."""

    def test_wellknown_endpoint(self, registry_client: TestClient) -> None:
        """Returns registry agent card with required fields."""
        resp = registry_client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "agent-registry"
        assert data["name"] == "A2A Agent Registry"
        assert "skills" in data
        assert len(data["skills"]) >= 1


class TestRegistryHealthEndpoint:
    """Tests for GET /health."""

    def test_health(self, registry_client: TestClient) -> None:
        """Returns 200 with status ok."""
        resp = registry_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestCreateAgent:
    """Tests for POST /agents (with mocked DB session)."""

    def test_create_agent(self, registry_client: TestClient) -> None:
        """POST /agents with valid body returns 201."""
        import os

        os.environ.setdefault("REGISTRY_DATABASE_URL", "sqlite+aiosqlite:///test.db")
        os.environ.setdefault("REGISTRY_API_KEY", "test-api-key")

        from registry.app.database import get_session
        from registry.app.main import app
        from registry.app.models import AgentCardRecord

        now = datetime.now(tz=timezone.utc)

        # Mock the DB session
        mock_session = AsyncMock()
        # simulate no existing agent
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # After commit+refresh, the record should have timestamps
        async def mock_refresh(record: AgentCardRecord) -> None:
            record.created_at = now
            record.updated_at = now
            record.id = "fake-uuid"

        mock_session.refresh = mock_refresh

        async def _mock_get_session():  # type: ignore[no-untyped-def]
            yield mock_session

        app.dependency_overrides[get_session] = _mock_get_session

        try:
            payload = {
                "id": "test-agent-01",
                "name": "Test Agent",
                "version": "1.0.0",
                "baseUrl": "http://test-agent:8080",
                "description": "A test agent",
                "skills": [{"id": "test", "name": "Test Skill", "description": "Does testing"}],
                "capabilities": {"streaming": False},
            }
            resp = registry_client.post("/agents", json=payload)
            assert resp.status_code == 201
            data = resp.json()
            assert data["name"] == "Test Agent"
        finally:
            app.dependency_overrides.pop(get_session, None)


class TestGetAgents:
    """Tests for GET /agents (with mocked DB session)."""

    def test_get_agents(self, registry_client: TestClient) -> None:
        """GET /agents returns list with total count."""
        import os

        os.environ.setdefault("REGISTRY_DATABASE_URL", "sqlite+aiosqlite:///test.db")
        os.environ.setdefault("REGISTRY_API_KEY", "test-api-key")

        from registry.app.database import get_session
        from registry.app.main import app

        mock_session = AsyncMock()

        # Mock list query: empty list
        mock_result_list = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result_list.scalars.return_value = mock_scalars

        # Mock count query
        mock_result_count = MagicMock()
        mock_result_count.scalar_one.return_value = 0

        mock_session.execute.side_effect = [mock_result_list, mock_result_count]

        async def _mock_get_session():  # type: ignore[no-untyped-def]
            yield mock_session

        app.dependency_overrides[get_session] = _mock_get_session

        try:
            resp = registry_client.get("/agents")
            assert resp.status_code == 200
            data = resp.json()
            assert "agents" in data
            assert data["total"] == 0
            assert isinstance(data["agents"], list)
        finally:
            app.dependency_overrides.pop(get_session, None)
