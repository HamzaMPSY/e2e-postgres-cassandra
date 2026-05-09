from __future__ import annotations

import unittest
from unittest.mock import patch

from server import (
    MetricsCollector,
    connector_metrics,
    debezium_jolokia_metrics,
    debezium_labels,
    label_value,
    numeric,
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
