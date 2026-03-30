"""Locust load testing scenarios for AI-SRE Platform.

Scenarios:
1. Concurrent LLM Requests — throughput and latency of LiteLLM Gateway
2. Provider Failover — behavior when a provider goes down
3. Peak Load (Stress Test) — find saturation point
4. Multi-Alert Storm — SRE Agent under concurrent alerts

Usage:
    # Scenario 1: LLM Gateway load
    locust -f tests/load/locustfile.py LLMUser --host http://localhost:4000

    # Scenario 4: Multi-alert storm
    locust -f tests/load/locustfile.py AlertStormUser --host http://localhost:8002

    # Web UI: http://localhost:8089
"""

import os
import time
import uuid

from locust import HttpUser, between, task, tag


LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-master-changeme")
MODEL = os.environ.get("LOAD_TEST_MODEL", "gpt-oss-120b")


class LLMUser(HttpUser):
    """Scenario 1 & 3: Concurrent LLM requests to LiteLLM Gateway.

    Sends chat completion requests with varying max_tokens.
    """

    wait_time = between(0.5, 2)

    @tag("chat", "non-stream")
    @task(3)
    def chat_completion(self) -> None:
        """Non-streaming chat completion request."""
        self.client.post(
            "/v1/chat/completions",
            json={
                "model": MODEL,
                "messages": [
                    {"role": "user", "content": "Explain CPU load average in 2 sentences"},
                ],
                "max_tokens": 100,
                "stream": False,
            },
            headers={"Authorization": f"Bearer {LITELLM_KEY}"},
            name="/v1/chat/completions [non-stream]",
        )

    @tag("chat", "stream")
    @task(2)
    def chat_completion_stream(self) -> None:
        """Streaming chat completion — measures TTFT."""
        start = time.monotonic()
        first_chunk_time = None

        with self.client.post(
            "/v1/chat/completions",
            json={
                "model": MODEL,
                "messages": [
                    {"role": "user", "content": "What is SRE? Answer briefly."},
                ],
                "max_tokens": 150,
                "stream": True,
            },
            headers={"Authorization": f"Bearer {LITELLM_KEY}"},
            name="/v1/chat/completions [stream]",
            stream=True,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Status {response.status_code}")
                return
            for chunk in response.iter_lines():
                if first_chunk_time is None and chunk:
                    first_chunk_time = time.monotonic()
            response.success()

        if first_chunk_time:
            ttft_ms = (first_chunk_time - start) * 1000
            # Report TTFT as a custom metric via request event
            self.environment.events.request.fire(
                request_type="TTFT",
                name="time_to_first_token",
                response_time=ttft_ms,
                response_length=0,
                exception=None,
                context={},
            )

    @tag("models")
    @task(1)
    def list_models(self) -> None:
        """List available models — lightweight health indicator."""
        self.client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {LITELLM_KEY}"},
            name="/v1/models",
        )


class AlertStormUser(HttpUser):
    """Scenario 4: Multi-alert storm — concurrent alerts to SRE Agent.

    Sends Zabbix-style alerts to /webhooks/zabbix.
    Tests deduplication, concurrency limits, and investigation throughput.
    """

    wait_time = between(1, 5)

    _alert_counter = 0

    @tag("alert", "unique")
    @task(3)
    def send_unique_alert(self) -> None:
        """Send a unique alert (should trigger investigation)."""
        AlertStormUser._alert_counter += 1
        alert_id = f"storm-{uuid.uuid4().hex[:8]}"

        triggers = [
            "CPU usage > 90%",
            "Memory usage > 85%",
            "Disk usage > 95%",
            "HTTP endpoint response time > 5s",
        ]
        trigger = triggers[AlertStormUser._alert_counter % len(triggers)]

        self.client.post(
            "/webhooks/zabbix",
            json={
                "alert_id": alert_id,
                "host": "playground",
                "trigger": trigger,
                "severity": "high",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "description": f"Load test alert: {trigger}",
            },
            name="/webhooks/zabbix [unique]",
        )

    @tag("alert", "duplicate")
    @task(1)
    def send_duplicate_alert(self) -> None:
        """Send a duplicate alert (should be deduplicated)."""
        self.client.post(
            "/webhooks/zabbix",
            json={
                "alert_id": "storm-duplicate-fixed",
                "host": "playground",
                "trigger": "CPU usage > 90%",
                "severity": "high",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "description": "Duplicate alert for dedup testing",
            },
            name="/webhooks/zabbix [duplicate]",
        )

    @tag("health")
    @task(1)
    def check_health(self) -> None:
        """Check agent health and metrics."""
        self.client.get("/health", name="/health")
