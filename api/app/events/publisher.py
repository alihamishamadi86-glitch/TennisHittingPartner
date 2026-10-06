import asyncio
from functools import lru_cache
from typing import Protocol

from google.cloud import pubsub_v1

from app.core.config import get_settings


class Publisher(Protocol):
    async def publish(self, topic: str, data: bytes, attributes: dict[str, str]) -> str: ...


class PubSubPublisher:
    def __init__(self, project_id: str) -> None:
        self._project_id = project_id
        self._client = pubsub_v1.PublisherClient()

    async def publish(self, topic: str, data: bytes, attributes: dict[str, str]) -> str:
        topic_path = self._client.topic_path(self._project_id, topic)
        future = self._client.publish(topic_path, data, **attributes)
        message_id: str = await asyncio.to_thread(future.result, timeout=30)
        return message_id


class InMemoryPublisher:
    """Test double that records published messages."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, bytes, dict[str, str]]] = []

    async def publish(self, topic: str, data: bytes, attributes: dict[str, str]) -> str:
        self.messages.append((topic, data, attributes))
        return str(len(self.messages))


@lru_cache
def get_publisher() -> Publisher:
    return PubSubPublisher(get_settings().gcp_project_id)
