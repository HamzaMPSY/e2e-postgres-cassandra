from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from server import (
    MetricsCollector,
    connector_metrics,
    data_quality_metrics,
    debezium_jolokia_metrics,
    debezium_labels,
    label_value,
    numeric,
    prometheus_metric_sum,
)


class ExporterTest(unittest.TestCase):
    def test_connector_metrics_render_running_state(self) -> None:
        metrics = connector_metrics(
            "postgres-orders-local",
            {
                "connector": {"state": "RUNNING"},
                "tasks": [{"id": 0, "state": "RUNNING"}],
            },
        )

        self.assertIn(
            'omnicare_connector_running{connector="postgres-orders-local"} 1',
            metrics,
        )
        self.assertIn(
            'omnicare_connector_task_running{connector="postgres-orders-local",task="0"} 1',
            metrics,
        )

    def test_label_value_escapes_prometheus_labels(self) -> None:
        self.assertEqual(label_value('bad"value\nx'), 'bad\\"value x')

    def test_numeric_falls_back_to_zero(self) -> None:
        self.assertEqual(numeric("12.5"), 12.5)
        self.assertEqual(numeric("not-a-number"), 0.0)

    def test_collector_renders_static_exporter_metric(self) -> None:
        collector = MetricsCollector("http://connect.invalid", "http://dashboard.invalid")

        metrics = collector.collect()

        self.assertIn("omnicare_exporter_up 1", metrics)
        self.assertIn("omnicare_kafka_connect_up 0", metrics)
        self.assertIn("omnicare_debezium_jmx_up 0", metrics)
        self.assertIn("omnicare_dashboard_api_up 0", metrics)

    def test_data_quality_metrics_render_overall_and_checks(self) -> None:
        metrics = data_quality_metrics(
            {
                "overallStatus": "warn",
                "checks": [
                    {"name": "dashboard_queries_ok", "status": "pass"},
                    {"name": "pipeline_event_freshness", "status": "warn"},
                ],
            }
        )

        self.assertIn('omnicare_data_quality_overall_status{status="warn"} 1', metrics)
        self.assertIn(
            'omnicare_data_quality_check_passed{check="dashboard_queries_ok",status="pass"} 1',
            metrics,
        )
        self.assertIn(
            'omnicare_data_quality_check_passed{check="pipeline_event_freshness",status="warn"} 0',
            metrics,
        )
        self.assertIn(
            'omnicare_data_quality_check_status{check="pipeline_event_freshness",status="warn"} 1',
            metrics,
        )

    def test_data_quality_metrics_render_numeric_details(self) -> None:
        metrics = data_quality_metrics(
            {
                "overallStatus": "fail",
                "checks": [
                    {
                        "name": "serving_payment_amounts_valid",
                        "status": "fail",
                        "details": {"totalInvalidFacts": 2},
                    }
                ],
            }
        )

        self.assertIn(
            'omnicare_data_quality_check_detail_value{check="serving_payment_amounts_valid",metric="totalInvalidFacts"} 2.0',
            metrics,
        )

    def test_prometheus_metric_sum_aggregates_labeled_metrics(self) -> None:
        text = """
omnicare_transformer_validation_rejects_total{error_code="a"} 1
omnicare_transformer_validation_rejects_total{error_code="b"} 2
"""
        self.assertEqual(
            prometheus_metric_sum(text, "omnicare_transformer_validation_rejects_total"),
            3,
        )

    def test_collector_reexports_transformer_quality_counts(self) -> None:
        def fake_http_text(url: str) -> str:
            self.assertEqual(url, "http://transformer:8090/metrics")
            return """
omnicare_transformer_dlq_records_total{source_topic="a"} 4
omnicare_transformer_validation_rejects_total{error_code="negative_number"} 3
"""

        collector = MetricsCollector(
            "http://connect.invalid",
            "http://dashboard.invalid",
            transformer_metrics_url="http://transformer:8090/metrics",
        )

        with patch("server.http_text", side_effect=fake_http_text):
            metrics = collector.collect()

        self.assertIn("omnicare_quality_dlq_records_total 4.0", metrics)
        self.assertIn("omnicare_quality_quarantine_records_total 3.0", metrics)

    def test_prometheus_alerts_cover_dlq_and_quarantine_spikes(self) -> None:
        root = Path(__file__).resolve().parents[3]
        content = (
            root
            / "observability"
            / "prometheus"
            / "rules"
            / "omnicare-alerts.yml"
        ).read_text(encoding="utf-8")

        for expected in (
            "OmniCareTransformerValidationRejects",
            "omnicare_transformer_validation_rejects_total",
            "OmniCareDlqSpike",
            "omnicare_quality_dlq_records_total",
            "OmniCareQuarantineSpike",
            "omnicare_quality_quarantine_records_total",
        ):
            self.assertIn(expected, content)

    def test_debezium_labels_extract_connector_context_and_domain(self) -> None:
        labels = debezium_labels(
            "debezium.postgres:type=connector-metrics,context=streaming,server=cdc.local.omnicare.postgres"
        )

        self.assertEqual(
            labels,
            '{connector="cdc.local.omnicare.postgres",context="streaming",domain="debezium.postgres"}',
        )

    def test_debezium_jolokia_metrics_render_lag_and_throughput(self) -> None:
        def fake_http_json(url: str):
            if "/search/" in url:
                return {
                    "value": [
                        "debezium.mysql:type=connector-metrics,context=streaming,server=cdc.local.omnicare.mysql"
                    ]
                }
            return {
                "value": {
                    "MilliSecondsBehindSource": 250,
                    "TotalNumberOfEventsSeen": 42,
                    "NumberOfEventsFiltered": 3,
                }
            }

        with patch("server.http_json", side_effect=fake_http_json):
            metrics = debezium_jolokia_metrics("http://connect:8778/jolokia")

        self.assertIn(
            'omnicare_debezium_source_lag_milliseconds{connector="cdc.local.omnicare.mysql",context="streaming",domain="debezium.mysql"} 250.0',
            metrics,
        )
        self.assertIn(
            'omnicare_debezium_events_seen_total{connector="cdc.local.omnicare.mysql",context="streaming",domain="debezium.mysql"} 42.0',
            metrics,
        )


if __name__ == "__main__":
    unittest.main()
