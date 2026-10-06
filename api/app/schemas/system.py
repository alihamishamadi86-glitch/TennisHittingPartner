import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SystemPingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    received_at: datetime | None
