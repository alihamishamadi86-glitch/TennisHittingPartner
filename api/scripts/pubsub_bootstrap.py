"""Create topics and push subscriptions on the local Pub/Sub emulator.

Mirrors what Terraform provisions in GCP: per event type a topic, a dead-letter topic and a
push subscription to the worker. Idempotent — safe to run on every `docker compose up`.

Usage: PUBSUB_EMULATOR_HOST=localhost:8085 python -m scripts.pubsub_bootstrap
"""

import os
import sys

from google.api_core.exceptions import AlreadyExists
from google.cloud import pubsub_v1

from app.core.config import get_settings
from app.events.catalog import EVENT_TYPES, topic_name


def main() -> None:
    if not os.environ.get("PUBSUB_EMULATOR_HOST"):
        sys.exit("Refusing to run: PUBSUB_EMULATOR_HOST is not set (this script is for local only)")

    project = get_settings().gcp_project_id
    push_endpoint = os.environ.get("WORKER_PUSH_ENDPOINT", "http://worker:8001/pubsub/push")
    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()

    for event_type in EVENT_TYPES:
        topic = publisher.topic_path(project, topic_name(event_type))
        dead_letter = publisher.topic_path(project, f"{topic_name(event_type)}.dlq")
        for path in (topic, dead_letter):
            try:
                publisher.create_topic(name=path)
                print(f"created topic {path}")
            except AlreadyExists:
                pass

        subscription = subscriber.subscription_path(project, f"{topic_name(event_type)}.worker")
        try:
            subscriber.create_subscription(
                request={
                    "name": subscription,
                    "topic": topic,
                    "push_config": {"push_endpoint": push_endpoint},
                    "ack_deadline_seconds": 60,
                    "dead_letter_policy": {
                        "dead_letter_topic": dead_letter,
                        "max_delivery_attempts": 10,
                    },
                }
            )
            print(f"created subscription {subscription} -> {push_endpoint}")
        except AlreadyExists:
            pass


if __name__ == "__main__":
    main()
