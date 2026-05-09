from __future__ import annotations

import logging
import time
from typing import Any

from .cassandra_writer import CassandraStarWriter
from .dlq import DlqProducer, FailedRecord
from .star_schema import to_star_rows


LOGGER = logging.getLogger(__name__)


class TransformerService:
    def __init__(self, consumer: Any, writer: CassandraStarWriter, dlq: DlqProducer):
        self._consumer = consumer
        self._writer = writer
        self._dlq = dlq

    def process_message(self, message: Any) -> int:
        try:
            rows = to_star_rows(message.topic(), message.value())
            written = self._writer.write_rows(rows)
            self._consumer.commit(message=message, asynchronous=False)
            LOGGER.info(
                "Processed CDC message topic=%s partition=%s offset=%s rows=%s",
                message.topic(),
                message.partition(),
                message.offset(),
                written,
            )
            return written
        except Exception as exc:
            failed = FailedRecord.from_exception(message, exc)
            self._dlq.publish(failed)
            self._consumer.commit(message=message, asynchronous=False)
            LOGGER.exception(
                "CDC message sent to DLQ topic=%s partition=%s offset=%s",
                message.topic(),
                message.partition(),
                message.offset(),
            )
            return 0

    def run_forever(self, poll_timeout_seconds: float = 1.0) -> None:
        while True:
            message = self._consumer.poll(poll_timeout_seconds)
            if message is None:
                continue
            if message.error():
                raise RuntimeError(message.error())
            self.process_message(message)

    def run_until(
        self,
        *,
        max_messages: int,
        idle_timeout_seconds: float,
        poll_timeout_seconds: float = 1.0,
    ) -> int:
        processed = 0
        idle_started_at = time.monotonic()

        while processed < max_messages:
            message = self._consumer.poll(poll_timeout_seconds)
            if message is None:
                if time.monotonic() - idle_started_at >= idle_timeout_seconds:
                    break
                continue
            if message.error():
                raise RuntimeError(message.error())

            idle_started_at = time.monotonic()
            self.process_message(message)
            processed += 1

        return processed
