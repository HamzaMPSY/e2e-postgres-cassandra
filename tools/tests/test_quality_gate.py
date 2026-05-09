from __future__ import annotations

import time
import unittest

from quality_gate import evaluate_snapshot


class QualityGateTest(unittest.TestCase):
    def test_accepts_passing_snapshot(self) -> None:
        failures = evaluate_snapshot(
            {
                "generatedAt": int(time.time()),
                "dataQuality": {
                    "overallStatus": "pass",
                    "checks": [{"name": "dashboard_queries_ok", "status": "pass"}],
                },
            },
            max_snapshot_age_seconds=60,
            allow_warnings=False,
        )

        self.assertEqual(failures, [])

    def test_rejects_failing_quality_check(self) -> None:
        failures = evaluate_snapshot(
            {
                "generatedAt": int(time.time()),
                "dataQuality": {
                    "overallStatus": "fail",
                    "checks": [
                        {"name": "order_payment_reconciliation", "status": "fail"}
                    ],
                },
            },
            max_snapshot_age_seconds=60,
            allow_warnings=False,
        )

        self.assertIn("dataQuality overallStatus=fail", failures)
        self.assertIn("quality check failed: order_payment_reconciliation", failures)

    def test_rejects_stale_snapshot(self) -> None:
        failures = evaluate_snapshot(
            {
                "generatedAt": int(time.time()) - 120,
                "dataQuality": {
                    "overallStatus": "pass",
                    "checks": [{"name": "dashboard_queries_ok", "status": "pass"}],
                },
            },
            max_snapshot_age_seconds=60,
            allow_warnings=False,
        )

        self.assertTrue(any("snapshot is stale" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
