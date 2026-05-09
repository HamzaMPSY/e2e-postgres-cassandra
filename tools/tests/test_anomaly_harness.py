from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class AnomalyHarnessTest(unittest.TestCase):
    def test_anomaly_harness_has_valid_bash_syntax(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            ["bash", "-n", str(root / "scripts" / "anomaly-e2e.sh")],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_anomaly_harness_contract_is_documented_in_script(self) -> None:
        root = Path(__file__).resolve().parents[2]
        content = (root / "scripts" / "anomaly-e2e.sh").read_text(encoding="utf-8")

        for expected in (
            "--skip-start",
            "--skip-register-connectors",
            "--cleanup",
            "--report-file",
            "postgres negative order quantity",
            "postgres null product id",
            "mysql null amount",
            "mysql negative payment amount",
            "mysql negative refund amount",
            "mongo null required fields",
            "mongo missing ticket id",
            "mongo invalid opened_at",
            "PAY-ANOM-OVERPAY",
            "PAY-ANOM-NEGATIVE",
            "PAY-ANOM-NULLPAID",
            "REF-ANOM-NEGATIVE",
            "TCK-ANOM-NULL-CUSTOMER",
            "TCK-ANOM-BAD-DATE",
            "dlq.local.omnicare.transformer",
            "fact_payment_by_day",
            "fact_support_case_by_customer",
            "python -m omnicare_cdc.main",
            "tools/quality_gate.py",
            "artifacts/anomaly-report.json",
            "--dry-run",
        ):
            self.assertIn(expected, content)

    def test_anomaly_harness_dry_run_prints_pipeline(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            [
                str(root / "scripts" / "anomaly-e2e.sh"),
                "--dry-run",
                "--env-file",
                str(root / ".env.example"),
                "--transformer-max-messages",
                "10",
                "--timeout-seconds",
                "30",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scripts/register-connectors.sh", result.stdout)
        self.assertIn("verify source rejects", result.stdout)
        self.assertIn("insert accepted anomaly rows", result.stdout)
        self.assertIn("python -m omnicare_cdc.main", result.stdout)
        self.assertIn("tools/quality_gate.py", result.stdout)
        self.assertIn("artifacts/anomaly-report.json", result.stdout)

    def test_anomaly_harness_dry_run_respects_skip_register(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            [
                str(root / "scripts" / "anomaly-e2e.sh"),
                "--dry-run",
                "--skip-register-connectors",
                "--env-file",
                str(root / ".env.example"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("scripts/register-connectors.sh", result.stdout)


if __name__ == "__main__":
    unittest.main()
