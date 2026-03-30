"""Database engine and session factory."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from registry.app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""

    pass


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """Yield an async database session.

    Yields:
        AsyncSession: Database session that auto-closes after use.
    """
    async with async_session() as session:
        yield session
