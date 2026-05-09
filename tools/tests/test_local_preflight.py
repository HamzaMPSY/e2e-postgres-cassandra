from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import local_preflight
from local_preflight import (
    CheckResult,
    REQUIRED_ENV_KEYS,
    parse_env_file,
    planned_checks,
    run_preflight,
    validate_env_file,
)


class LocalPreflightTest(unittest.TestCase):
    def test_current_example_env_has_required_keys(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = validate_env_file(root, Path(".env.example"))

        self.assertEqual(result.status, "pass", result.detail)

    def test_detects_missing_required_env_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.write_text(
                "\n".join(
                    f"{key}=value"
                    for key in sorted(REQUIRED_ENV_KEYS - {"POSTGRES_DB"})
                ),
                encoding="utf-8",
            )

            result = validate_env_file(root, Path(".env"))

        self.assertEqual(result.status, "fail")
        self.assertIn("POSTGRES_DB", result.detail)

    def test_parse_env_file_handles_comments_and_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "# comment\nPOSTGRES_DB='orders'\nMYSQL_DATABASE=\"billing\"\n",
                encoding="utf-8",
            )

            values = parse_env_file(env_file)

        self.assertEqual(values["POSTGRES_DB"], "orders")
        self.assertEqual(values["MYSQL_DATABASE"], "billing")

    def test_dry_run_plan_can_skip_podman(self) -> None:
        checks = planned_checks(Path(".env.example"), skip_podman=True)

        self.assertIn("skip Podman checks", checks)
        self.assertNotIn("run podman version", checks)

    def test_run_preflight_dry_run_does_not_write_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_file = Path(temp_dir) / "preflight.json"

            exit_code, report = run_preflight(
                root=Path(__file__).resolve().parents[2],
                env_file=Path(".env.example"),
                report_file=report_file,
                skip_podman=True,
                dry_run=True,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "planned")
        self.assertFalse(report_file.exists())

    def test_shell_entrypoint_dry_run(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            [
                str(root / "scripts" / "local-preflight.sh"),
                "--dry-run",
                "--env-file",
                ".env.example",
                "--skip-podman",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Local preflight dry-run plan", result.stdout)
        self.assertIn("validate env file", result.stdout)

    def test_skip_podman_writes_report_for_static_preflight(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temp_dir:
            report_file = Path(temp_dir) / "preflight.json"

            with patch.object(
                local_preflight,
                "command_availability",
                return_value=[CheckResult("command:python", "pass", "/usr/bin/python")],
            ), patch.object(
                local_preflight,
                "run_command",
                return_value=CheckResult("static_validation:1", "pass", "ok"),
            ):
                exit_code, report = run_preflight(
                    root=root,
                    env_file=Path(".env.example"),
                    report_file=report_file,
                    skip_podman=True,
                    dry_run=False,
                )

            stored = json.loads(report_file.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0, report)
        self.assertEqual(stored["status"], "passed")
        self.assertTrue(any(check["name"] == "podman" for check in stored["checks"]))


if __name__ == "__main__":
    unittest.main()
