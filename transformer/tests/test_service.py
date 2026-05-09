from __future__ import annotations

import logging
import json
import unittest

from omnicare_cdc.service import TransformerService
from omnicare_cdc.metrics import MetricsRegistry


class FakeMessage:
    def __init__(
        self,
        value: bytes,
        topic: str = "cdc.local.omnicare.postgres.public.customers",
    ):
        self._value = value
        self._topic = topic

    def topic(self) -> str:
        return self._topic

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
        metrics = MetricsRegistry()
        service = TransformerService(consumer=consumer, writer=writer, dlq=dlq, metrics=metrics)

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
        self.assertIn(
            'omnicare_transformer_messages_processed_total{result="success"} 1',
            metrics.render_prometheus(),
        )

    def test_publishes_dlq_and_commits_on_failure(self) -> None:
        consumer = FakeConsumer()
        writer = FakeWriter(fail=True)
        dlq = FakeDlq()
        metrics = MetricsRegistry()
        service = TransformerService(consumer=consumer, writer=writer, dlq=dlq, metrics=metrics)

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
        self.assertIn(
            'omnicare_transformer_messages_processed_total{result="dlq"} 1',
            metrics.render_prometheus(),
        )

    def test_validation_rejects_negative_payment_before_write(self) -> None:
        consumer = FakeConsumer()
        writer = FakeWriter()
        dlq = FakeDlq()
        metrics = MetricsRegistry()
        service = TransformerService(consumer=consumer, writer=writer, dlq=dlq, metrics=metrics)

        written = service.process_message(
            _message(
                "cdc.local.omnicare.mysql.billing.payments",
                "payments",
                {
                    "payment_id": "payment-negative",
                    "invoice_id": "invoice-1",
                    "order_id": "order-1",
                    "customer_id": "customer-1",
                    "payment_status": "captured",
                    "payment_method": "card",
                    "amount_cents": -1,
                    "paid_at": "2026-05-09T10:00:00+00:00",
                },
            )
        )

        self.assertEqual(written, 0)
        self.assertEqual(writer.written, 0)
        self.assertEqual(consumer.committed, 1)
        self.assertEqual(len(dlq.records), 1)
        self.assertEqual(dlq.records[0].metadata["validation_error_code"], "negative_number")
        self.assertEqual(dlq.records[0].metadata["table"], "fact_payment_by_day")
        self.assertIn(
            'omnicare_transformer_validation_rejects_total{source_topic="cdc.local.omnicare.mysql.billing.payments",target_table="fact_payment_by_day",error_code="negative_number"} 1',
            metrics.render_prometheus(),
        )

    def test_validation_rejects_unknown_payment_status(self) -> None:
        consumer = FakeConsumer()
        writer = FakeWriter()
        dlq = FakeDlq()
        service = TransformerService(consumer=consumer, writer=writer, dlq=dlq)

        written = service.process_message(
            _message(
                "cdc.local.omnicare.mysql.billing.payments",
                "payments",
                {
                    "payment_id": "payment-unknown-status",
                    "invoice_id": "invoice-1",
                    "order_id": "order-1",
                    "customer_id": "customer-1",
                    "payment_status": "settled",
                    "payment_method": "card",
                    "amount_cents": 1000,
                    "paid_at": "2026-05-09T10:00:00+00:00",
                },
            )
        )

        self.assertEqual(written, 0)
        self.assertEqual(writer.written, 0)
        self.assertEqual(dlq.records[0].metadata["validation_error_code"], "unknown_enum_value")
        self.assertEqual(dlq.records[0].metadata["field"], "payment_status")

    def test_validation_allows_payment_with_null_paid_at_and_updated_at_fallback(self) -> None:
        consumer = FakeConsumer()
        writer = FakeWriter()
        dlq = FakeDlq()
        service = TransformerService(consumer=consumer, writer=writer, dlq=dlq)

        written = service.process_message(
            _message(
                "cdc.local.omnicare.mysql.billing.payments",
                "payments",
                {
                    "payment_id": "payment-pending",
                    "invoice_id": "invoice-1",
                    "order_id": "order-1",
                    "customer_id": "customer-1",
                    "payment_status": "pending",
                    "payment_method": "insurance",
                    "amount_cents": 1000,
                    "paid_at": None,
                    "updated_at": "2026-05-09T10:00:00+00:00",
                },
            )
        )

        self.assertEqual(written, 1)
        self.assertEqual(writer.written, 1)
        self.assertEqual(dlq.records, [])

    def test_validation_rejects_null_support_customer(self) -> None:
        consumer = FakeConsumer()
        writer = FakeWriter()
        dlq = FakeDlq()
        service = TransformerService(consumer=consumer, writer=writer, dlq=dlq)

        written = service.process_message(
            _message(
                "cdc.local.omnicare.mongo.engagement.support_tickets",
                "support_tickets",
                {
                    "ticket_id": "ticket-null-customer",
                    "customer_id": None,
                    "priority": "critical",
                    "status": "open",
                    "opened_at": {"$date": 1778235462000},
                    "sla_due_at": None,
                    "closed_at": None,
                },
                source={"collection": "support_tickets", "ord": 7},
            )
        )

        self.assertEqual(written, 0)
        self.assertEqual(writer.written, 0)
        self.assertEqual(dlq.records[0].metadata["validation_error_code"], "required_field_missing")
        self.assertEqual(dlq.records[0].metadata["field"], "customer_id")

    def test_missing_mongo_ticket_id_is_dlqed(self) -> None:
        consumer = FakeConsumer()
        writer = FakeWriter()
        dlq = FakeDlq()
        service = TransformerService(consumer=consumer, writer=writer, dlq=dlq)

        written = service.process_message(
            _message(
                "cdc.local.omnicare.mongo.engagement.support_tickets",
                "support_tickets",
                {
                    "customer_id": "customer-1",
                    "priority": "critical",
                    "status": "open",
                    "opened_at": {"$date": 1778235462000},
                },
                source={"collection": "support_tickets", "ord": 8},
            )
        )

        self.assertEqual(written, 0)
        self.assertEqual(writer.written, 0)
        self.assertIn("KeyError", dlq.records[0].error)
        self.assertIsNone(dlq.records[0].metadata)

    def test_bad_mongo_timestamp_is_dlqed(self) -> None:
        consumer = FakeConsumer()
        writer = FakeWriter()
        dlq = FakeDlq()
        service = TransformerService(consumer=consumer, writer=writer, dlq=dlq)

        written = service.process_message(
            _message(
                "cdc.local.omnicare.mongo.engagement.support_tickets",
                "support_tickets",
                {
                    "ticket_id": "ticket-bad-date",
                    "customer_id": "customer-1",
                    "priority": "critical",
                    "status": "open",
                    "opened_at": "not-a-date",
                },
                source={"collection": "support_tickets", "ord": 9},
            )
        )

        self.assertEqual(written, 0)
        self.assertEqual(writer.written, 0)
        self.assertIn("ValueError", dlq.records[0].error)
        self.assertIsNone(dlq.records[0].metadata)

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

    def test_run_until_continues_after_validation_failure(self) -> None:
        invalid = _message(
            "cdc.local.omnicare.mysql.billing.payments",
            "payments",
            {
                "payment_id": "payment-negative",
                "invoice_id": "invoice-1",
                "order_id": "order-1",
                "customer_id": "customer-1",
                "payment_status": "captured",
                "payment_method": "card",
                "amount_cents": -1,
                "paid_at": "2026-05-09T10:00:00+00:00",
            },
        )
        valid = _message(
            "cdc.local.omnicare.mysql.billing.payments",
            "payments",
            {
                "payment_id": "payment-valid",
                "invoice_id": "invoice-1",
                "order_id": "order-1",
                "customer_id": "customer-1",
                "payment_status": "captured",
                "payment_method": "card",
                "amount_cents": 1000,
                "paid_at": "2026-05-09T10:00:00+00:00",
            },
        )
        consumer = PollingFakeConsumer([invalid, valid])
        writer = FakeWriter()
        dlq = FakeDlq()
        service = TransformerService(consumer=consumer, writer=writer, dlq=dlq)

        processed = service.run_until(
            max_messages=2,
            idle_timeout_seconds=0.1,
            poll_timeout_seconds=0.01,
        )

        self.assertEqual(processed, 2)
        self.assertEqual(consumer.committed, 2)
        self.assertEqual(writer.written, 1)
        self.assertEqual(len(dlq.records), 1)

def _message(
    topic: str,
    table: str,
    after: dict[str, object],
    source: dict[str, object] | None = None,
) -> FakeMessage:
    source_payload = source or {"table": table, "file": "mysql-bin.000001", "pos": 10}
    value = json.dumps(
        {
            "payload": {
                "op": "c",
                "ts_ms": 1710000000000,
                "source": source_payload,
                "after": after,
            }
        }
    ).encode("utf-8")
    return FakeMessage(value, topic=topic)


if __name__ == "__main__":
    unittest.main()
