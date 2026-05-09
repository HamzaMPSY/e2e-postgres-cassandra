from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class RecoveryHarnessTest(unittest.TestCase):
    def test_recovery_harness_has_valid_bash_syntax(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            ["bash", "-n", str(root / "scripts" / "recover-bad-facts.sh")],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_recovery_harness_contract_is_documented_in_script(self) -> None:
        root = Path(__file__).resolve().parents[2]
        content = (root / "scripts" / "recover-bad-facts.sh").read_text(
            encoding="utf-8"
        )

        for expected in (
            "--payment-id-prefix",
            "--refund-id-prefix",
            "--ticket-id-prefix",
            "--source-position",
            "--report-file",
            "--yes",
            "--dry-run",
            "fact_payment_by_day",
            "fact_support_case_by_customer",
            "source_position",
            "tools/quality_gate.py",
            "artifacts/recovery-report.json",
        ):
            self.assertIn(expected, content)

    def test_recovery_harness_dry_run_prints_plan_without_podman(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            [
                str(root / "scripts" / "recover-bad-facts.sh"),
                "--dry-run",
                "--payment-id-prefix",
                "PAY-ANOM-",
                "--ticket-id-prefix",
                "TCK-ANOM-",
                "--source-position",
                "file:mysql-bin.000001|pos:1",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dry-run recovery plan", result.stdout)
        self.assertIn("payment_id_prefix=PAY-ANOM-", result.stdout)
        self.assertIn("ticket_id_prefix=TCK-ANOM-", result.stdout)
        self.assertIn("source_position=file:mysql-bin.000001", result.stdout)
        self.assertIn("artifacts/recovery-report.json", result.stdout)

    def test_recovery_harness_rejects_broad_prefixes(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            [
                str(root / "scripts" / "recover-bad-facts.sh"),
                "--dry-run",
                "--payment-id-prefix",
                "PAY",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("at least 6 characters", result.stderr)


if __name__ == "__main__":
    unittest.main()
