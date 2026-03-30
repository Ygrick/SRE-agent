"""Structured logging configuration for Registry."""

import structlog


def setup_logging() -> None:
    """Configure structlog for JSON output with log level and timestamps."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


setup_logging()
