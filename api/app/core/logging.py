"""Structured JSON logging compatible with Cloud Logging.

Cloud Logging parses `severity` and `logging.googleapis.com/trace` from JSON written to
stdout, which groups all log lines of a request under its trace in the console.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

_project_id: str = ""


class CloudLoggingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "logger": record.name,
        }
        if trace_id := trace_id_var.get():
            entry["logging.googleapis.com/trace"] = f"projects/{_project_id}/traces/{trace_id}"
        if extra := getattr(record, "extra_fields", None):
            entry.update(extra)
        if record.exc_info:
            entry["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str, project_id: str) -> None:
    global _project_id
    _project_id = project_id
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CloudLoggingFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


def parse_trace_header(header: str | None) -> str | None:
    """Extract the trace id from `X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=1`."""
    if not header:
        return None
    return header.split("/", 1)[0] or None
