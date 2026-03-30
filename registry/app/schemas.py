"""Pydantic schemas for Agent Registry API."""

from datetime import datetime

from pydantic import BaseModel, Field


class AgentCardCreate(BaseModel):
    """Request body for creating/updating an Agent Card.

    Attributes:
        id: Unique agent identifier.
        name: Human-readable agent name.
        version: Semantic version.
        base_url: Agent service endpoint.
        description: Optional agent description.
        skills: List of agent skills.
        capabilities: Agent capabilities flags.
        security_schemes: Security schemes map.
    """

    id: str = Field(description="Unique agent identifier")
    name: str = Field(description="Human-readable agent name")
    version: str = Field(description="Semantic version")
    base_url: str = Field(alias="baseUrl", description="Agent service endpoint URL")
    description: str | None = Field(default=None, description="Agent description")
    skills: list[dict] = Field(default_factory=list, description="Agent skills")
    capabilities: dict = Field(default_factory=dict, description="Agent capabilities")
    security_schemes: dict = Field(
        default_factory=dict,
        alias="securitySchemes",
        description="Security schemes",
    )

    model_config = {"populate_by_name": True}


class AgentCardResponse(BaseModel):
    """Response body for an Agent Card.

    Attributes:
        id: Unique agent identifier.
        name: Human-readable agent name.
        version: Semantic version.
        base_url: Agent service endpoint.
        description: Optional agent description.
        skills: Agent skills.
        capabilities: Agent capabilities.
        security_schemes: Security schemes.
        created_at: Registration timestamp.
        updated_at: Last update timestamp.
    """

    id: str
    name: str
    version: str
    base_url: str = Field(alias="baseUrl")
    description: str | None = None
    skills: list[dict] = Field(default_factory=list)
    capabilities: dict = Field(default_factory=dict)
    security_schemes: dict = Field(default_factory=dict, alias="securitySchemes")
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True, "from_attributes": True}


class AgentCardListResponse(BaseModel):
    """Paginated list of Agent Cards.

    Attributes:
        agents: List of agent cards.
        total: Total number of agents.
    """

    agents: list[AgentCardResponse]
    total: int
