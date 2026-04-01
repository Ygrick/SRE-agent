"""Tests for agent.app.main: FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient

from agent.app.main import _metrics, _processed_alerts, app


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset global state before each test."""
    _processed_alerts.clear()
    _metrics["investigations_total"] = 0
    _metrics["investigations_completed"] = 0
    _metrics["investigations_failed"] = 0
    _metrics["investigations_active"] = 0


@pytest.fixture()
def client() -> TestClient:
    """Create a FastAPI TestClient without triggering lifespan.

    Lifespan attempts A2A registration which requires network access.
    """
    return TestClient(app, raise_server_exceptions=False)


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_endpoint(self, client: TestClient) -> None:
        """GET /health returns 200 with status ok."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "metrics" in data


class TestWebhookEndpoint:
    """Tests for POST /webhooks/zabbix."""

    def test_webhook_accepts_valid_alert(
        self, client: TestClient, sample_alert_payload: dict
    ) -> None:
        """Valid alert payload returns 202 with investigation_id."""
        resp = client.post("/webhooks/zabbix", json=sample_alert_payload)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["alert_id"] == sample_alert_payload["alert_id"]
        assert data["investigation_id"] != ""

    def test_webhook_rejects_invalid(self, client: TestClient) -> None:
        """Missing required fields returns 422."""
        resp = client.post("/webhooks/zabbix", json={"alert_id": "x"})
        assert resp.status_code == 422

    def test_webhook_dedup(
        self, client: TestClient, sample_alert_payload: dict
    ) -> None:
        """Sending the same alert_id twice returns skipped_duplicate."""
        client.post("/webhooks/zabbix", json=sample_alert_payload)
        resp = client.post("/webhooks/zabbix", json=sample_alert_payload)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "skipped_duplicate"

    def test_webhook_increments_counter(
        self, client: TestClient, sample_alert_payload: dict
    ) -> None:
        """Accepted alert increments investigations_total counter."""
        client.post("/webhooks/zabbix", json=sample_alert_payload)
        assert _metrics["investigations_total"] == 1


class TestMetricsEndpoint:
    """Tests for GET /metrics."""

    def test_metrics_endpoint(self, client: TestClient) -> None:
        """GET /metrics returns Prometheus text format."""
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        body = resp.text
        assert "sre_agent_investigations_total" in body
        assert "sre_agent_investigations_completed" in body
        assert "sre_agent_investigations_failed" in body
        assert "sre_agent_investigations_active" in body
