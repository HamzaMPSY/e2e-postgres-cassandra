from __future__ import annotations

import unittest
from unittest.mock import patch

from quality import quality_report
from server import (
    ORDER_TO_CASH,
    PAYMENT_HEALTH,
    REVENUE_BY_DAY,
    SUPPORT_RISK,
    _freshness_window_seconds,
    _rows_from_response,
    _summary,
)


class ServerTest(unittest.TestCase):
    def test_rows_from_response_maps_column_names(self) -> None:
        response = {
            "columns": [{"name": "order_day"}, {"name": "gross_revenue"}],
            "data": [["2026-05-08", 6079.8]],
        }

        self.assertEqual(
            _rows_from_response(response),
            [{"order_day": "2026-05-08", "gross_revenue": 6079.8}],
        )

    def test_summary_rolls_up_dashboard_metrics(self) -> None:
        summary = _summary(
            revenue=[{"gross_revenue": 100.5, "order_lines": 3}],
            payments=[{"amount": 80, "payment_count": 2}],
            support=[{"ticket_count": 4}],
            order_cash=[{"open_amount": 20.5}],
        )

        self.assertEqual(summary["grossRevenue"], 100.5)
        self.assertEqual(summary["orderLines"], 3)
        self.assertEqual(summary["paymentAmount"], 80)
        self.assertEqual(summary["paymentCount"], 2)
        self.assertEqual(summary["supportCases"], 4)
        self.assertEqual(summary["openAmount"], 20.5)

    def test_payment_health_includes_refunds(self) -> None:
        self.assertIn("fact_refund_by_day", PAYMENT_HEALTH)
        self.assertIn("'refunded' AS payment_status", PAYMENT_HEALTH)

    def test_freshness_window_falls_back_for_invalid_config(self) -> None:
        with patch.dict(
            "os.environ",
            {"DASHBOARD_FRESHNESS_MAX_AGE_SECONDS": "not-an-int"},
        ):
            self.assertGreater(_freshness_window_seconds(), 0)

    def test_dashboard_queries_expose_freshness_columns(self) -> None:
        for sql in (REVENUE_BY_DAY, PAYMENT_HEALTH, SUPPORT_RISK, ORDER_TO_CASH):
            self.assertIn("last_event_ts", sql)

    def test_quality_report_passes_coherent_snapshot(self) -> None:
        report = quality_report(
            generated_at=1_000,
            revenue=[
                {
                    "gross_revenue": 100,
                    "order_lines": 2,
                    "units_ordered": 4,
                    "last_event_ts": "1970-01-01T00:16:30+00:00",
                }
            ],
            payments=[
                {
                    "payment_status": "captured",
                    "amount": 80,
                    "payment_count": 1,
                    "last_event_ts": "1970-01-01T00:16:31+00:00",
                }
            ],
            support=[
                {
                    "ticket_count": 1,
                    "last_event_ts": "1970-01-01T00:16:32+00:00",
                }
            ],
            order_cash=[{"order_id": "o1", "open_amount": 20}],
            max_event_age_seconds=60,
        )

        self.assertEqual(report["overallStatus"], "pass")

    def test_quality_report_fails_overpaid_orders(self) -> None:
        report = quality_report(
            generated_at=1_000,
            revenue=[{"gross_revenue": 100, "order_lines": 1, "units_ordered": 1}],
            payments=[{"payment_status": "captured", "amount": 120, "payment_count": 1}],
            support=[],
            order_cash=[{"order_id": "o1", "open_amount": -20}],
        )

        self.assertEqual(report["overallStatus"], "fail")
        failed_checks = {
            check["name"] for check in report["checks"] if check["status"] == "fail"
        }
        self.assertIn("order_payment_reconciliation", failed_checks)


if __name__ == "__main__":
    unittest.main()
