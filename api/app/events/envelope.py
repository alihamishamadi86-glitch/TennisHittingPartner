import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    """Wire format for every event published to Pub/Sub."""

    event_id: uuid.UUID
    type: str
    version: int = 1
    occurred_at: datetime
    data: dict[str, Any] = Field(default_factory=dict)
