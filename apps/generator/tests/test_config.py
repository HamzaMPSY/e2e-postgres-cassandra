from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from omnicare_generator.config import GeneratorConfig, RunConfig


class GeneratorConfigTest(unittest.TestCase):
    def test_reads_scenario_controls_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GENERATOR_RANDOM_SEED": "42",
                "GENERATOR_FAILURE_RATE": "0.25",
                "GENERATOR_REFUND_RATE": "0.15",
                "GENERATOR_SLA_BREACH_RATE": "0.30",
                "GENERATOR_INVENTORY_SOURCE": "none",
            },
            clear=False,
        ):
            config = GeneratorConfig.from_env()

        self.assertEqual(config.random_seed, 42)
        self.assertEqual(config.failure_rate, 0.25)
        self.assertEqual(config.refund_rate, 0.15)
        self.assertEqual(config.sla_breach_rate, 0.30)
        self.assertEqual(config.inventory_source, "none")

    def test_rejects_invalid_inventory_source(self) -> None:
        with patch.dict(
            os.environ,
            {"GENERATOR_INVENTORY_SOURCE": "oracle-and-postgres"},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                GeneratorConfig.from_env()

    def test_run_config_prefers_max_events_over_iterations(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GENERATOR_ITERATIONS": "10",
                "GENERATOR_MAX_EVENTS": "3",
                "GENERATOR_RATE_PER_SECOND": "2",
                "GENERATOR_SLEEP_SECONDS": "9",
            },
            clear=False,
        ):
            config = RunConfig.from_env()

        self.assertEqual(config.event_limit(), 3)
        self.assertEqual(config.event_interval_seconds(), 0.5)


if __name__ == "__main__":
    unittest.main()
