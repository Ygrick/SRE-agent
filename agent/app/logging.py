"""Structured logging configuration for SRE Agent."""

import logging
import sys

import structlog


def setup_logging() -> None:
    """Configure structlog for JSON output to stderr."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

    # Also configure stdlib logging to go to stderr
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=logging.INFO,
    )


setup_logging()
