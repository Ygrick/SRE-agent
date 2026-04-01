"""Shared fixtures for SRE-agent tests.

IMPORTANT: This module sets up test isolation BEFORE any app module is imported.
The project's .env file contains variables that conflict with pydantic-settings,
so we must change cwd or patch env_file to prevent it from being read.
"""

import os
import sys

import pytest

# Change to a temp directory so pydantic-settings won't find the project .env
_original_cwd = os.getcwd()


def _setup_test_env() -> None:
    """Set environment variables needed by AgentSettings before import."""
    import tempfile

    # Use a temp dir as cwd so .env is not found by pydantic-settings
    test_dir = tempfile.mkdtemp(prefix="sre_agent_test_")
    os.chdir(test_dir)

    defaults = {
        "AGENT_HOST": "127.0.0.1",
        "AGENT_PORT": "8002",
        "AGENT_GATEWAY_URL": "http://test-gateway:4000",
        "AGENT_GATEWAY_API_KEY": "test-key",
        "AGENT_REGISTRY_URL": "http://test-registry:8001",
        "AGENT_REGISTRY_API_KEY": "test-registry-key",
        "AGENT_TELEGRAM_BOT_TOKEN": "",
        "AGENT_TELEGRAM_CHAT_ID": "",
        "AGENT_LANGFUSE_PUBLIC_KEY": "",
        "AGENT_LANGFUSE_SECRET_KEY": "",
        "AGENT_QDRANT_URL": "http://test-qdrant:6333",
        "AGENT_QDRANT_COLLECTION": "runbooks",
        "AGENT_CODEX_MODEL": "test-model",
        "AGENT_SSH_USER": "test-user",
        "AGENT_SSH_KEY_PATH": "/tmp/fake_key",
        "AGENT_LANGFUSE_HOST": "http://test-langfuse:3000",
        "AGENT_MAX_SHELL_COMMANDS": "15",
        "AGENT_INVESTIGATION_TIMEOUT_SECONDS": "300",
        # Registry settings
        "REGISTRY_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "REGISTRY_API_KEY": "test-api-key",
    }
    for key, val in defaults.items():
        os.environ[key] = val


_setup_test_env()


@pytest.fixture()
def sample_alert_dict() -> dict:
    """Return a sample Zabbix alert dict for testing."""
    return {
        "alert_id": "alert-001",
        "host": "web-server-01",
        "trigger": "CPU usage is too high",
        "severity": "high",
        "timestamp": "2025-06-01T12:00:00Z",
        "description": "CPU usage above 90% for 5 minutes",
    }


@pytest.fixture()
def sample_alert_payload() -> dict:
    """Return a sample alert JSON payload for API tests."""
    return {
        "alert_id": "alert-002",
        "host": "db-server-01",
        "trigger": "Memory usage critical",
        "severity": "disaster",
        "timestamp": "2025-06-01T12:05:00Z",
        "description": "Available memory below 100MB",
    }
