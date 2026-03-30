"""A2A Agent Registry — FastAPI application."""

import hmac
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from registry.app.config import settings
from registry.app.database import Base, engine, get_session
from registry.app.models import AgentCardRecord
from registry.app.schemas import AgentCardCreate, AgentCardListResponse, AgentCardResponse

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: create tables on startup.

    Args:
        app: FastAPI application instance.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("registry_started", port=settings.port)
    yield
    await engine.dispose()


app = FastAPI(title="A2A Agent Registry", version="0.1.0", lifespan=lifespan)


# === Auth Middleware ===


async def verify_api_key(request: Request) -> None:
    """Verify the Authorization header contains a valid API key.

    Args:
        request: Incoming HTTP request.

    Raises:
        HTTPException: 401 if key is missing or invalid.
    """
    if request.url.path in ("/health", "/.well-known/agent-card.json"):
        return
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(token, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# === Helper ===


def _record_to_response(record: AgentCardRecord) -> AgentCardResponse:
    """Convert a database record to an API response.

    Args:
        record: Agent card database record.

    Returns:
        Pydantic response model.
    """
    card = record.card_json
    return AgentCardResponse(
        id=record.agent_id,
        name=record.name,
        version=record.version,
        baseUrl=record.base_url,
        description=record.description,
        skills=card.get("skills", []),
        capabilities=card.get("capabilities", {}),
        securitySchemes=card.get("securitySchemes", {}),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# === Endpoints ===


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        Status dict.
    """
    return {"status": "ok"}


@app.post("/agents", response_model=AgentCardResponse, status_code=201)
async def register_agent(
    body: AgentCardCreate,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
) -> AgentCardResponse:
    """Register a new A2A agent.

    Args:
        body: Agent Card data.
        session: Database session.
        _auth: Auth dependency (side-effect only).

    Returns:
        Created agent card.

    Raises:
        HTTPException: 409 if agent_id already exists.
    """
    existing = await session.execute(
        select(AgentCardRecord).where(AgentCardRecord.agent_id == body.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Agent '{body.id}' already registered")

    record = AgentCardRecord(
        agent_id=body.id,
        name=body.name,
        version=body.version,
        base_url=body.base_url,
        description=body.description,
        card_json=body.model_dump(by_alias=True),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    logger.info("agent_registered", agent_id=body.id, name=body.name)
    return _record_to_response(record)


@app.get("/agents", response_model=AgentCardListResponse)
async def list_agents(
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
) -> AgentCardListResponse:
    """List all registered agents.

    Args:
        session: Database session.
        _auth: Auth dependency.

    Returns:
        List of agent cards with total count.
    """
    result = await session.execute(select(AgentCardRecord).order_by(AgentCardRecord.name))
    records = result.scalars().all()
    total_result = await session.execute(select(func.count(AgentCardRecord.id)))
    total = total_result.scalar_one()
    return AgentCardListResponse(
        agents=[_record_to_response(r) for r in records],
        total=total,
    )


@app.get("/agents/{agent_id}", response_model=AgentCardResponse)
async def get_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
) -> AgentCardResponse:
    """Get a specific agent by ID.

    Args:
        agent_id: Unique agent identifier.
        session: Database session.
        _auth: Auth dependency.

    Returns:
        Agent card.

    Raises:
        HTTPException: 404 if agent not found.
    """
    result = await session.execute(
        select(AgentCardRecord).where(AgentCardRecord.agent_id == agent_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return _record_to_response(record)


@app.put("/agents/{agent_id}", response_model=AgentCardResponse)
async def update_agent(
    agent_id: str,
    body: AgentCardCreate,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
) -> AgentCardResponse:
    """Update an existing agent's card.

    Args:
        agent_id: Agent to update.
        body: New agent card data.
        session: Database session.
        _auth: Auth dependency.

    Returns:
        Updated agent card.

    Raises:
        HTTPException: 404 if agent not found.
    """
    result = await session.execute(
        select(AgentCardRecord).where(AgentCardRecord.agent_id == agent_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    record.name = body.name
    record.version = body.version
    record.base_url = body.base_url
    record.description = body.description
    record.card_json = body.model_dump(by_alias=True)
    await session.commit()
    await session.refresh(record)
    logger.info("agent_updated", agent_id=agent_id)
    return _record_to_response(record)


@app.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
) -> None:
    """Delete an agent from the registry.

    Args:
        agent_id: Agent to delete.
        session: Database session.
        _auth: Auth dependency.

    Raises:
        HTTPException: 404 if agent not found.
    """
    result = await session.execute(
        select(AgentCardRecord).where(AgentCardRecord.agent_id == agent_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    await session.execute(
        delete(AgentCardRecord).where(AgentCardRecord.agent_id == agent_id)
    )
    await session.commit()
    logger.info("agent_deleted", agent_id=agent_id)


@app.get("/.well-known/agent-card.json")
async def well_known_agent_card(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Well-known endpoint returning the registry's own Agent Card (A2A discovery).

    Args:
        session: Database session.

    Returns:
        Registry Agent Card dict.
    """
    return {
        "id": "agent-registry",
        "name": "A2A Agent Registry",
        "version": "0.1.0",
        "baseUrl": f"http://agent-registry:{settings.port}",
        "description": "A2A Agent Registry for AI-SRE Platform. Provides CRUD for Agent Cards.",
        "capabilities": {"a2a": True},
        "skills": [
            {
                "id": "register-agent",
                "name": "Register Agent",
                "description": "Register a new A2A agent with its Agent Card",
            },
            {
                "id": "list-agents",
                "name": "List Agents",
                "description": "List all registered agents",
            },
        ],
    }
