from __future__ import annotations

import unittest
from datetime import UTC, date, datetime

from omnicare_cdc.guardrails import BusinessGuardrails
from omnicare_cdc.models import StarRow
from omnicare_cdc.validation import BusinessRules, RowValidationError, validate_star_rows


class BusinessGuardrailsTest(unittest.TestCase):
    def test_allows_partial_payment_against_known_order_total(self) -> None:
        guardrails = BusinessGuardrails(BusinessRules())
        guardrails.observe([_order_line(order_id="order-1", amount_cents=10_000)])

        rows = guardrails.validate([_payment(order_id="order-1", amount_cents=5_000)])

        self.assertEqual(len(rows), 1)

    def test_allows_exact_payment_against_known_order_total(self) -> None:
        guardrails = BusinessGuardrails(BusinessRules())
        guardrails.observe([_order_line(order_id="order-1", amount_cents=10_000)])

        rows = guardrails.validate([_payment(order_id="order-1", amount_cents=10_000)])

        self.assertEqual(len(rows), 1)

    def test_rejects_overpayment_against_known_order_total(self) -> None:
        guardrails = BusinessGuardrails(BusinessRules(payment_overpay_tolerance_cents=100))
        guardrails.observe([_order_line(order_id="order-1", amount_cents=10_000)])

        with self.assertRaises(RowValidationError) as raised:
            guardrails.validate([_payment(order_id="order-1", amount_cents=10_101)])

        self.assertEqual(
            raised.exception.issues[0].code,
            "payment_amount_exceeds_order_total",
        )

    def test_deferred_mode_allows_unknown_references_for_cross_topic_ordering(self) -> None:
        guardrails = BusinessGuardrails(BusinessRules(reference_validation_mode="deferred"))

        rows = guardrails.validate([_payment(order_id="order-not-seen", amount_cents=1000)])

        self.assertEqual(len(rows), 1)

    def test_strict_mode_rejects_unknown_order_and_customer_references(self) -> None:
        guardrails = BusinessGuardrails(BusinessRules(reference_validation_mode="strict"))

        with self.assertRaises(RowValidationError) as raised:
            guardrails.validate([_payment(order_id="order-not-seen", amount_cents=1000)])

        codes = {issue.code for issue in raised.exception.issues}
        self.assertEqual(codes, {"unknown_order_reference", "unknown_customer_reference"})

    def test_max_payment_amount_cap_rejects_impossible_local_amount(self) -> None:
        rules = BusinessRules(max_payment_amount_cents=10_000)

        with self.assertRaises(RowValidationError) as raised:
            validate_star_rows([_payment(order_id="order-1", amount_cents=10_001)], rules)

        self.assertEqual(
            raised.exception.issues[0].code,
            "payment_amount_exceeds_configured_max",
        )


def _order_line(order_id: str, amount_cents: int) -> StarRow:
    return StarRow(
        table="fact_order_line_by_day",
        key={"order_day": date(2026, 5, 9), "fact_id": f"line-{order_id}"},
        values={
            "order_id": order_id,
            "order_item_id": f"item-{order_id}",
            "customer_id": "customer-1",
            "product_id": "product-1",
            "channel": "portal",
            "quantity": 1,
            "unit_price_cents": amount_cents,
            "gross_amount_cents": amount_cents,
            "order_status": "confirmed",
            "source_topic": "cdc.local.omnicare.postgres.public.order_items",
            "source_position": "lsn:1",
            "event_ts": datetime(2026, 5, 9, tzinfo=UTC),
            "op": "c",
        },
    )


def _payment(order_id: str, amount_cents: int) -> StarRow:
    return StarRow(
        table="fact_payment_by_day",
        key={"payment_day": date(2026, 5, 9), "fact_id": f"payment-{order_id}"},
        values={
            "payment_id": f"pay-{order_id}",
            "invoice_id": f"invoice-{order_id}",
            "order_id": order_id,
            "customer_id": "customer-1",
            "payment_status": "captured",
            "payment_method": "card",
            "amount_cents": amount_cents,
            "source_topic": "cdc.local.omnicare.mysql.billing.payments",
            "source_position": "file:mysql-bin.000001|pos:1",
            "event_ts": datetime(2026, 5, 9, tzinfo=UTC),
            "op": "c",
        },
    )


if __name__ == "__main__":
    unittest.main()
