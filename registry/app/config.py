"""Registry configuration via pydantic-settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RegistrySettings(BaseSettings):
    """A2A Agent Registry configuration.

    Args:
        host: Server bind address.
        port: Server bind port.
        database_url: PostgreSQL async connection string.
        api_key: Shared API key for registry access.
    """

    model_config = SettingsConfigDict(env_prefix="REGISTRY_", env_file=".env")

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8001)
    database_url: str = Field(description="PostgreSQL async connection string")
    api_key: str = Field(description="API key for registry access")


settings = RegistrySettings()
