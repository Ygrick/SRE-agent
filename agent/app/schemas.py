"""Pydantic schemas for SRE Agent API."""

from datetime import datetime

from pydantic import BaseModel, Field


class ZabbixAlert(BaseModel):
    """Incoming Zabbix webhook payload.

    Attributes:
        alert_id: Unique alert/event identifier.
        host: Host where the alert originated.
        trigger: Trigger name/description.
        severity: Alert severity level.
        timestamp: Alert timestamp.
        description: Detailed alert description.
    """

    alert_id: str = Field(description="Unique alert ID")
    host: str = Field(description="Affected host")
    trigger: str = Field(description="Trigger name")
    severity: str = Field(description="Alert severity (high, disaster, warning, etc.)")
    timestamp: str = Field(description="Alert timestamp")
    description: str = Field(default="", description="Alert description")


class InvestigationResponse(BaseModel):
    """Response for accepted investigation.

    Attributes:
        status: Acceptance status.
        alert_id: Alert being investigated.
        investigation_id: Unique investigation ID.
    """

    status: str = Field(default="accepted")
    alert_id: str
    investigation_id: str
