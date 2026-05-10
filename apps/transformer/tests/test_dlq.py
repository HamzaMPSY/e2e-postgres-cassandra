from __future__ import annotations

import json
import unittest

from omnicare_cdc.dlq import DlqProducer, FailedRecord


class FakeProducer:
    def __init__(self) -> None:
        self.produced: list[dict[str, object]] = []
        self.flushes = 0

    def produce(self, topic: str, key: str | None, value: str) -> None:
        self.produced.append({"topic": topic, "key": key, "value": value})

    def flush(self) -> None:
        self.flushes += 1


class DlqTest(unittest.TestCase):
    def test_redacts_failed_record_payload_by_default(self) -> None:
        record = FailedRecord(
            topic="cdc.local.omnicare.mysql.billing.payments",
            partition=0,
            offset=42,
            key="payment-1",
            value='{"customer_id":"customer-1"}',
            error="ValueError: bad row",
        )

        payload = json.loads(record.to_json())

        self.assertEqual(payload["key"], "[redacted]")
        self.assertEqual(payload["value"], "[redacted]")

    def test_dlq_producer_omits_key_when_payloads_are_redacted(self) -> None:
        producer = FakeProducer()
        dlq = DlqProducer(producer=producer, topic="dlq.local.omnicare.transformer")
        record = FailedRecord(
            topic="topic",
            partition=0,
            offset=1,
            key="secret-key",
            value="secret-value",
            error="error",
        )

        dlq.publish(record)

        self.assertEqual(producer.produced[0]["key"], None)
        self.assertEqual(json.loads(producer.produced[0]["value"])["value"], "[redacted]")
        self.assertEqual(producer.flushes, 1)

    def test_failed_record_includes_validation_metadata(self) -> None:
        record = FailedRecord(
            topic="cdc.local.omnicare.mysql.billing.payments",
            partition=0,
            offset=42,
            key="payment-1",
            value='{"customer_id":"customer-1"}',
            error="RowValidationError: negative amount",
            metadata={
                "validation_error_code": "negative_number",
                "table": "fact_payment_by_day",
                "field": "amount_cents",
            },
        )

        payload = json.loads(record.to_json())

        self.assertEqual(payload["metadata"]["validation_error_code"], "negative_number")
        self.assertEqual(payload["metadata"]["table"], "fact_payment_by_day")


if __name__ == "__main__":
    unittest.main()
