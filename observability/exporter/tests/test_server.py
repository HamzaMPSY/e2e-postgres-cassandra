from __future__ import annotations

import unittest

from server import MetricsCollector, connector_metrics, label_value, numeric


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
        self.assertIn("omnicare_dashboard_api_up 0", metrics)


if __name__ == "__main__":
    unittest.main()
