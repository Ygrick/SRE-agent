"""Tests for deduplication logic in agent.app.main."""

import time
from unittest.mock import patch

from agent.app.main import DEDUP_TTL_SECONDS, _is_duplicate, _processed_alerts


class TestDeduplication:
    """Tests for _is_duplicate()."""

    def setup_method(self) -> None:
        """Clear dedup state before each test."""
        _processed_alerts.clear()

    def test_is_duplicate_first_time(self) -> None:
        """First occurrence of an alert_id returns False."""
        assert _is_duplicate("dup-001") is False

    def test_is_duplicate_second_time(self) -> None:
        """Second occurrence of same alert_id returns True."""
        _is_duplicate("dup-002")
        assert _is_duplicate("dup-002") is True

    def test_dedup_ttl_expiry(self) -> None:
        """Expired entries are cleaned up, allowing re-processing."""
        _is_duplicate("dup-003")
        # Simulate expiry by backdating the timestamp
        _processed_alerts["dup-003"] = time.time() - DEDUP_TTL_SECONDS - 1

        # Next call should clean expired entry and return False
        assert _is_duplicate("dup-003") is False

    def test_dedup_different_ids(self) -> None:
        """Different alert_ids are not treated as duplicates."""
        _is_duplicate("dup-100")
        assert _is_duplicate("dup-200") is False
