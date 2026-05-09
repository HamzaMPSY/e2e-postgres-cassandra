from __future__ import annotations

import logging
import time
from typing import Any

from .cassandra_writer import CassandraStarWriter
from .dlq import DlqProducer, FailedRecord
from .metrics import MetricsRegistry
from .star_schema import to_star_rows


LOGGER = logging.getLogger(__name__)


class TransformerService:
    def __init__(
        self,
        consumer: Any,
        writer: CassandraStarWriter,
        dlq: DlqProducer,
        metrics: MetricsRegistry | None = None,
    ):
        self._consumer = consumer
        self._writer = writer
        self._dlq = dlq
        self._metrics = metrics

    def process_message(self, message: Any) -> int:
        try:
            rows = to_star_rows(message.topic(), message.value())
            write_started_at = time.perf_counter()
            try:
                written = self._writer.write_rows(rows)
            finally:
                self._observe_write_latency(time.perf_counter() - write_started_at)
            self._consumer.commit(message=message, asynchronous=False)
            self._record_success(written)
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
            self._record_dlq(message.topic())
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

    def _observe_write_latency(self, elapsed_seconds: float) -> None:
        if self._metrics is not None:
            self._metrics.observe_cassandra_write(elapsed_seconds)

    def _record_success(self, rows_written: int) -> None:
        if self._metrics is not None:
            self._metrics.record_success(rows_written)

    def _record_dlq(self, source_topic: str) -> None:
        if self._metrics is not None:
            self._metrics.record_dlq(source_topic)
