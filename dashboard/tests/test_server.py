from __future__ import annotations

import unittest

from server import PAYMENT_HEALTH, _rows_from_response, _summary


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


if __name__ == "__main__":
    unittest.main()
