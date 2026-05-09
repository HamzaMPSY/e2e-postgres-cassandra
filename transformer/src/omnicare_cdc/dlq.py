from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class FailedRecord:
    topic: str
    partition: int | None
    offset: int | None
    key: str | None
    value: str | None
    error: str

    @classmethod
    def from_exception(cls, message: Any, exc: BaseException) -> FailedRecord:
        return cls(
            topic=_call(message, "topic"),
            partition=_call(message, "partition"),
            offset=_call(message, "offset"),
            key=_decode(_call(message, "key")),
            value=_decode(_call(message, "value")),
            error=f"{type(exc).__name__}: {exc}",
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "failed_at": datetime.now(tz=UTC).isoformat(),
                "topic": self.topic,
                "partition": self.partition,
                "offset": self.offset,
                "key": self.key,
                "value": self.value,
                "error": self.error,
                "traceback": traceback.format_exc(),
            },
            default=str,
            sort_keys=True,
        )


class DlqProducer:
    def __init__(self, producer: Any, topic: str):
        self._producer = producer
        self._topic = topic

    def publish(self, failed: FailedRecord) -> None:
        self._producer.produce(
            self._topic,
            key=failed.key,
            value=failed.to_json(),
        )
        self._producer.flush()


def connect_dlq_producer(bootstrap_servers: str, topic: str) -> DlqProducer:
    try:
        from confluent_kafka import Producer
    except ImportError as exc:
        raise RuntimeError("confluent-kafka is required to publish DLQ records") from exc

    return DlqProducer(
        producer=Producer({"bootstrap.servers": bootstrap_servers}),
        topic=topic,
    )


def _call(obj: Any, method_name: str) -> Any:
    method = getattr(obj, method_name, None)
    return method() if callable(method) else None


def _decode(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)

