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

    def to_json(self, include_payloads: bool = False) -> str:
        key = self.key if include_payloads else _redacted(self.key)
        value = self.value if include_payloads else _redacted(self.value)
        return json.dumps(
            {
                "failed_at": datetime.now(tz=UTC).isoformat(),
                "topic": self.topic,
                "partition": self.partition,
                "offset": self.offset,
                "key": key,
                "value": value,
                "error": self.error,
                "traceback": traceback.format_exc(),
            },
            default=str,
            sort_keys=True,
        )


class DlqProducer:
    def __init__(self, producer: Any, topic: str, include_payloads: bool = False):
        self._producer = producer
        self._topic = topic
        self._include_payloads = include_payloads

    def publish(self, failed: FailedRecord) -> None:
        self._producer.produce(
            self._topic,
            key=failed.key if self._include_payloads else None,
            value=failed.to_json(include_payloads=self._include_payloads),
        )
        self._producer.flush()


def connect_dlq_producer(
    bootstrap_servers: str,
    topic: str,
    security_config: dict[str, str] | None = None,
    include_payloads: bool = False,
) -> DlqProducer:
    try:
        from confluent_kafka import Producer
    except ImportError as exc:
        raise RuntimeError("confluent-kafka is required to publish DLQ records") from exc

    producer_config = {"bootstrap.servers": bootstrap_servers}
    if security_config:
        producer_config.update(security_config)

    return DlqProducer(
        producer=Producer(producer_config),
        topic=topic,
        include_payloads=include_payloads,
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


def _redacted(value: str | None) -> str | None:
    return None if value is None else "[redacted]"
