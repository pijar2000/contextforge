"""Structured JSON logging with run/request correlation identifiers."""

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime

_context: contextvars.ContextVar[dict] = contextvars.ContextVar("log_context", default={})


def bind_context(**values) -> None:
    """Attach fields (run_id, request_id, ...) to every log line in the current context."""
    _context.set({**_context.get(), **values})


def clear_context() -> None:
    _context.set({})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_context.get(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


def log_fields(logger: logging.Logger, level: int, message: str, **fields) -> None:
    logger.log(level, message, extra={"fields": fields})
