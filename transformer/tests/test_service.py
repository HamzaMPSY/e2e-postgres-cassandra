from __future__ import annotations

import logging
import unittest

from omnicare_cdc.service import TransformerService


class FakeMessage:
    def __init__(self, value: bytes):
        self._value = value

    def topic(self) -> str:
        return "cdc.local.omnicare.postgres.public.customers"

    def partition(self) -> int:
        return 0

    def offset(self) -> int:
        return 10

    def key(self) -> bytes:
        return b"customer-1"

    def value(self) -> bytes:
        return self._value

    def error(self) -> None:
        return None


class FakeConsumer:
    def __init__(self) -> None:
        self.committed = 0

    def commit(self, message: FakeMessage, asynchronous: bool) -> None:
        self.committed += 1


class PollingFakeConsumer(FakeConsumer):
    def __init__(self, messages: list[FakeMessage | None]) -> None:
        super().__init__()
        self.messages = messages

    def poll(self, timeout: float) -> FakeMessage | None:
        if not self.messages:
            return None
        return self.messages.pop(0)


class FakeWriter:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.written = 0

    def write_rows(self, rows: list[object]) -> int:
        if self.fail:
            raise RuntimeError("write failed")
        self.written += len(rows)
        return len(rows)


class FakeDlq:
    def __init__(self) -> None:
        self.records: list[object] = []

    def publish(self, failed: object) -> None:
        self.records.append(failed)


class TransformerServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)

    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)

    def test_commits_after_successful_write(self) -> None:
        consumer = FakeConsumer()
        writer = FakeWriter()
        dlq = FakeDlq()
        service = TransformerService(consumer=consumer, writer=writer, dlq=dlq)

        written = service.process_message(
            FakeMessage(
                b"""
                {
                  "payload": {
                    "op": "c",
                    "ts_ms": 1710000000000,
                    "source": {"table": "customers", "lsn": 1},
                    "after": {
                      "customer_id": "customer-1",
                      "hospital_name": "Central Hospital",
                      "segment": "enterprise",
                      "city": "Casablanca",
                      "country": "MA"
                    }
                  }
                }
                """
            )
        )

        self.assertEqual(written, 1)
        self.assertEqual(writer.written, 1)
        self.assertEqual(consumer.committed, 1)
        self.assertEqual(dlq.records, [])

    def test_publishes_dlq_and_commits_on_failure(self) -> None:
        consumer = FakeConsumer()
        writer = FakeWriter(fail=True)
        dlq = FakeDlq()
        service = TransformerService(consumer=consumer, writer=writer, dlq=dlq)

        written = service.process_message(
            FakeMessage(
                b"""
                {
                  "payload": {
                    "op": "c",
                    "source": {"table": "customers", "lsn": 1},
                    "after": {"customer_id": "customer-1"}
                  }
                }
                """
            )
        )

        self.assertEqual(written, 0)
        self.assertEqual(consumer.committed, 1)
        self.assertEqual(len(dlq.records), 1)

    def test_run_until_stops_at_max_messages(self) -> None:
        event = FakeMessage(
            b"""
            {
              "payload": {
                "op": "c",
                "ts_ms": 1710000000000,
                "source": {"table": "customers", "lsn": 1},
                "after": {
                  "customer_id": "customer-1",
                  "hospital_name": "Central Hospital",
                  "segment": "enterprise",
                  "city": "Casablanca",
                  "country": "MA"
                }
              }
            }
            """
        )
        consumer = PollingFakeConsumer([event, event])
        writer = FakeWriter()
        service = TransformerService(consumer=consumer, writer=writer, dlq=FakeDlq())

        processed = service.run_until(
            max_messages=1,
            idle_timeout_seconds=0.1,
            poll_timeout_seconds=0.01,
        )

        self.assertEqual(processed, 1)
        self.assertEqual(consumer.committed, 1)


if __name__ == "__main__":
    unittest.main()
