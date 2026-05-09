from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class DemoHarnessTest(unittest.TestCase):
    def test_demo_harness_has_valid_bash_syntax(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            ["bash", "-n", str(root / "scripts" / "demo-e2e.sh")],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_demo_harness_contract_is_documented_in_script(self) -> None:
        root = Path(__file__).resolve().parents[2]
        content = (root / "scripts" / "demo-e2e.sh").read_text(encoding="utf-8")

        for expected in (
            "podman compose",
            "scripts/register-connectors.sh",
            "omnicare_generator.main",
            "omnicare_cdc.main",
            "fact_order_line_by_day",
            "fact_payment_by_day",
            "fact_support_case_by_customer",
            "fact_inventory_movement_by_product",
            "http://localhost:18090/api/dashboard",
            "--dry-run",
        ):
            self.assertIn(expected, content)

    def test_demo_harness_dry_run_prints_pipeline(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            [
                str(root / "scripts" / "demo-e2e.sh"),
                "--dry-run",
                "--env-file",
                str(root / ".env.example"),
                "--max-events",
                "2",
                "--rate-per-second",
                "1",
                "--transformer-max-messages",
                "10",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("podman compose", result.stdout)
        self.assertIn("scripts/register-connectors.sh", result.stdout)
        self.assertIn("verify Cassandra row counts and dashboard API", result.stdout)


if __name__ == "__main__":
    unittest.main()
