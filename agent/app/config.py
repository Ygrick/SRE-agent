"""SRE Agent configuration via pydantic-settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """SRE Agent configuration.

    Attributes:
        host: Server bind address.
        port: Server bind port.
        gateway_url: LiteLLM Gateway URL.
        gateway_api_key: LiteLLM virtual key.
        registry_url: A2A Agent Registry URL.
        registry_api_key: Registry API key.
        qdrant_url: Qdrant vector DB URL.
        qdrant_collection: Qdrant collection name for runbooks.
        telegram_bot_token: Telegram Bot API token.
        telegram_chat_id: Target Telegram chat for reports.
        codex_model: Model name for Codex CLI.
        max_shell_commands: Max shell commands per investigation.
        investigation_timeout_seconds: Max investigation duration.
        playground_ssh_host: SSH host for playground.
        playground_ssh_user: SSH user for playground.
        playground_ssh_key_path: Path to SSH private key.
        langfuse_public_key: Langfuse public key.
        langfuse_secret_key: Langfuse secret key.
        langfuse_host: Langfuse server URL.
    """

    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=".env")

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8002)
    gateway_url: str = Field(default="http://litellm:4000")
    gateway_api_key: str = Field(default="", description="LiteLLM virtual key")
    registry_url: str = Field(default="http://agent-registry:8001")
    registry_api_key: str = Field(default="", description="Registry API key")
    qdrant_url: str = Field(default="http://qdrant:6333")
    qdrant_collection: str = Field(default="runbooks")
    telegram_bot_token: str = Field(default="", description="Telegram Bot API token")
    telegram_chat_id: str = Field(default="", description="Target chat for reports")
    codex_model: str = Field(default="qwen/qwen3.6-plus-preview:free")
    fallback_model: str = Field(default="gpt-oss-120b", description="Model for fallback LLM calls via LiteLLM")
    max_shell_commands: int = Field(default=15)
    investigation_timeout_seconds: int = Field(default=300)
    playground_ssh_host: str = Field(default="playground-app")
    playground_ssh_user: str = Field(default="sre-agent")
    playground_ssh_key_path: str = Field(default="/run/secrets/ssh/id_ed25519")
    langfuse_public_key: str = Field(default="", description="Langfuse public key")
    langfuse_secret_key: str = Field(default="", description="Langfuse secret key")
    langfuse_host: str = Field(default="http://langfuse:3000")


settings = AgentSettings()
