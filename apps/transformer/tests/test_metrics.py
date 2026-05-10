from __future__ import annotations

import unittest
from unittest.mock import patch

from omnicare_cdc.config import AppConfig
from omnicare_cdc.metrics import MetricsRegistry


class MetricsRegistryTest(unittest.TestCase):
    def test_renders_transformer_counters_and_latency(self) -> None:
        registry = MetricsRegistry()

        registry.record_success(rows_written=3)
        registry.record_dlq('cdc.local.bad"topic')
        registry.record_validation_reject(
            source_topic='cdc.local.bad"topic',
            target_table="fact_payment_by_day",
            error_code="negative_number",
        )
        registry.observe_cassandra_write(0.25)

        metrics = registry.render_prometheus()

        self.assertIn('omnicare_transformer_messages_processed_total{result="success"} 1', metrics)
        self.assertIn('omnicare_transformer_messages_processed_total{result="dlq"} 1', metrics)
        self.assertIn("omnicare_transformer_rows_written_total 3", metrics)
        self.assertIn(
            'omnicare_transformer_dlq_records_total{source_topic="cdc.local.bad\\"topic"} 1',
            metrics,
        )
        self.assertIn(
            'omnicare_transformer_validation_rejects_total{source_topic="cdc.local.bad\\"topic",target_table="fact_payment_by_day",error_code="negative_number"} 1',
            metrics,
        )
        self.assertIn("omnicare_transformer_cassandra_write_latency_seconds_count 1", metrics)
        self.assertIn("omnicare_transformer_cassandra_write_latency_seconds_sum 0.250000000", metrics)

    def test_metrics_config_can_be_disabled(self) -> None:
        with patch.dict("os.environ", {"TRANSFORMER_METRICS_ENABLED": "false"}, clear=False):
            config = AppConfig.from_env()

        self.assertFalse(config.metrics_enabled)


if __name__ == "__main__":
    unittest.main()
