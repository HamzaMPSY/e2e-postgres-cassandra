from __future__ import annotations

import unittest
from unittest.mock import patch

from quality import quality_report
from server import (
    ORDER_TO_CASH,
    PAYMENT_HEALTH,
    QUALITY_FINDINGS,
    REVENUE_BY_DAY,
    SUPPORT_RISK,
    _freshness_window_seconds,
    _prometheus_metric_sum,
    _quality_threshold,
    _rows_from_response,
    _summary,
    _warning_checks,
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

    def test_quality_findings_scans_serving_anomalies(self) -> None:
        for expected in (
            "negative_payment_facts",
            "negative_refund_facts",
            "null_customer_dimensions",
            "null_product_dimensions",
            "null_support_dimensions",
            "unknown_payment_enums",
            "unknown_inventory_enums",
            "dim_customer_by_id",
            "dim_product_by_id",
            "fact_payment_by_day",
            "fact_support_case_by_customer",
        ):
            self.assertIn(expected, QUALITY_FINDINGS)

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
            quality_findings=[
                {
                    "negative_payment_facts": 0,
                    "negative_refund_facts": 0,
                    "null_customer_dimensions": 0,
                    "null_product_dimensions": 0,
                    "null_order_dimensions": 0,
                    "null_payment_dimensions": 0,
                    "null_support_dimensions": 0,
                    "null_inventory_dimensions": 0,
                    "unknown_order_enums": 0,
                    "unknown_payment_enums": 0,
                    "unknown_refund_enums": 0,
                    "unknown_support_enums": 0,
                    "unknown_inventory_enums": 0,
                }
            ],
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

    def test_quality_report_fails_raw_bad_facts(self) -> None:
        report = quality_report(
            generated_at=1_000,
            revenue=[{"gross_revenue": 100, "order_lines": 1, "units_ordered": 1}],
            payments=[{"payment_status": "captured", "amount": 80, "payment_count": 1}],
            support=[{"ticket_count": 1}],
            order_cash=[{"order_id": "o1", "open_amount": 20}],
            quality_findings=[
                {
                    "negative_payment_facts": 1,
                    "negative_refund_facts": 0,
                    "null_customer_dimensions": 0,
                    "null_product_dimensions": 0,
                    "null_order_dimensions": 0,
                    "null_payment_dimensions": 0,
                    "null_support_dimensions": 1,
                    "null_inventory_dimensions": 0,
                    "unknown_order_enums": 0,
                    "unknown_payment_enums": 1,
                    "unknown_refund_enums": 0,
                    "unknown_support_enums": 0,
                    "unknown_inventory_enums": 0,
                }
            ],
        )

        self.assertEqual(report["overallStatus"], "fail")
        failed_checks = {
            check["name"] for check in report["checks"] if check["status"] == "fail"
        }
        self.assertIn("serving_payment_amounts_valid", failed_checks)
        self.assertIn("serving_required_dimensions_present", failed_checks)
        self.assertIn("serving_enum_values_known", failed_checks)

    def test_quality_report_can_warn_for_configured_non_critical_rules(self) -> None:
        report = quality_report(
            generated_at=1_000,
            revenue=[{"gross_revenue": 100, "order_lines": 1, "units_ordered": 1}],
            payments=[{"payment_status": "captured", "amount": 80, "payment_count": 1}],
            support=[{"ticket_count": 1}],
            order_cash=[{"order_id": "o1", "open_amount": 20}],
            operational_metrics={
                "telemetryAvailable": True,
                "dlqRecordCount": 3,
                "quarantineRecordCount": 2,
            },
            warning_checks={"dlq_quarantine_thresholds"},
            dlq_max_records=0,
            quarantine_max_records=0,
        )

        warning_checks = {
            check["name"] for check in report["checks"] if check["status"] == "warn"
        }
        self.assertEqual(report["overallStatus"], "warn")
        self.assertIn("dlq_quarantine_thresholds", warning_checks)

    def test_quality_env_helpers_parse_thresholds_and_warning_checks(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "DASHBOARD_DLQ_MAX_RECORDS": "7",
                "DASHBOARD_QUALITY_WARNING_CHECKS": "a,b, c ",
            },
        ):
            self.assertEqual(_quality_threshold("DASHBOARD_DLQ_MAX_RECORDS", 0), 7)
            self.assertEqual(_warning_checks(), {"a", "b", "c"})

    def test_prometheus_metric_sum_aggregates_labeled_metrics(self) -> None:
        text = """
# HELP ignored ignored
omnicare_transformer_dlq_records_total{source_topic="a"} 2
omnicare_transformer_dlq_records_total{source_topic="b"} 3
other_metric 99
"""
        self.assertEqual(
            _prometheus_metric_sum(text, "omnicare_transformer_dlq_records_total"),
            5,
        )


if __name__ == "__main__":
    unittest.main()
