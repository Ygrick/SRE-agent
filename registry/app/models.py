"""SQLAlchemy models for Agent Registry."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from registry.app.database import Base


class AgentCardRecord(Base):
    """Agent Card stored in the registry.

    Stores A2A Agent Card as JSONB along with indexable fields.

    Attributes:
        id: Internal UUID primary key.
        agent_id: Unique agent identifier (from Agent Card).
        name: Human-readable agent name.
        version: Semantic version string.
        base_url: Agent service endpoint URL.
        description: Optional agent description.
        card_json: Full Agent Card as JSONB.
        created_at: Record creation timestamp.
        updated_at: Last update timestamp.
    """

    __tablename__ = "agent_cards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    card_json: Mapped[dict] = mapped_column(JSONB, nullable=False)  # type: ignore[assignment]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
