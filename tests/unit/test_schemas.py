"""Tests for agent.app.schemas: ZabbixAlert and InvestigationResponse."""

import pytest
from pydantic import ValidationError

from agent.app.schemas import InvestigationResponse, ZabbixAlert


class TestZabbixAlert:
    """Tests for ZabbixAlert schema."""

    def test_zabbix_alert_valid(self) -> None:
        """Valid payload parses without errors."""
        alert = ZabbixAlert(
            alert_id="a-100",
            host="node-01",
            trigger="CPU high",
            severity="high",
            timestamp="2025-06-01T10:00:00Z",
            description="CPU above threshold",
        )
        assert alert.alert_id == "a-100"
        assert alert.host == "node-01"
        assert alert.trigger == "CPU high"
        assert alert.severity == "high"
        assert alert.description == "CPU above threshold"

    def test_zabbix_alert_missing_required(self) -> None:
        """Missing required fields raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ZabbixAlert(
                alert_id="a-101",
                # host is missing
                trigger="Disk full",
                severity="disaster",
                timestamp="2025-06-01T10:00:00Z",
            )
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "host" in field_names

    def test_zabbix_alert_optional_description(self) -> None:
        """Description is optional with empty string default."""
        alert = ZabbixAlert(
            alert_id="a-102",
            host="node-02",
            trigger="Service down",
            severity="warning",
            timestamp="2025-06-01T11:00:00Z",
        )
        assert alert.description == ""


class TestInvestigationResponse:
    """Tests for InvestigationResponse schema."""

    def test_investigation_response(self) -> None:
        """Response model validates correctly."""
        resp = InvestigationResponse(
            status="accepted",
            alert_id="a-200",
            investigation_id="inv-001",
        )
        assert resp.status == "accepted"
        assert resp.alert_id == "a-200"
        assert resp.investigation_id == "inv-001"

    def test_investigation_response_default_status(self) -> None:
        """Status defaults to 'accepted'."""
        resp = InvestigationResponse(
            alert_id="a-201",
            investigation_id="inv-002",
        )
        assert resp.status == "accepted"

    def test_investigation_response_missing_required(self) -> None:
        """Missing alert_id raises ValidationError."""
        with pytest.raises(ValidationError):
            InvestigationResponse(
                investigation_id="inv-003",
            )
