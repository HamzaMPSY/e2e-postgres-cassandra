from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import local_status
from local_status import (
    collect_artifact_status,
    collect_dashboard_quality,
    collect_endpoint_status,
    collect_podman_status,
    http_ok,
    planned_checks,
    run_status,
)


class LocalStatusTest(unittest.TestCase):
    def test_shell_entrypoint_dry_run(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            [str(root / "scripts" / "local-status.sh"), "--dry-run", "--skip-podman"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Local status dry-run plan", result.stdout)
        self.assertIn("Connectors: postgres-orders-local", result.stdout)
        self.assertIn("check dashboard data quality", result.stdout)

    def test_planned_checks_can_skip_podman(self) -> None:
        checks = planned_checks(skip_podman=True)

        self.assertIn("skip Podman containers", checks)
        self.assertNotIn("check local Podman containers", checks)

    def test_collect_artifact_status_reports_missing_files_as_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = collect_artifact_status(Path(temp_dir))

        self.assertEqual(result.status, "warn")
        self.assertIn("missing artifacts", result.detail)

    def test_collect_dashboard_quality_pass(self) -> None:
        payload = {
            "generatedAt": 1,
            "summary": {"orders": 3},
            "dataQuality": {"overallStatus": "pass", "checks": []},
        }

        with patch.object(local_status, "http_json", return_value=payload):
            result = collect_dashboard_quality("http://dashboard", 1)

        self.assertEqual(result.status, "pass")
        self.assertIn("overallStatus=pass", result.detail)

    def test_collect_endpoint_status_warns_when_endpoint_is_unavailable(self) -> None:
        with patch.object(local_status, "http_ok", side_effect=OSError("offline")):
            result = collect_endpoint_status(1)

        self.assertEqual(result.status, "warn")
        self.assertIn("unavailable endpoints", result.detail)

    def test_http_ok_treats_client_error_as_reachable(self) -> None:
        error = HTTPError("http://grafana", 401, "unauthorized", {}, None)

        with patch.object(local_status, "urlopen", side_effect=error):
            result = http_ok("http://grafana", 1)

        self.assertTrue(result)

    def test_collect_podman_status_can_be_skipped(self) -> None:
        result = collect_podman_status(Path.cwd(), 1, skip_podman=True)

        self.assertEqual(result.status, "skipped")

    def test_collect_podman_status_warns_on_unhealthy_container(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["podman"],
            returncode=0,
            stdout="omnicare-dashboard|Up 1 minute (unhealthy)\n",
            stderr="",
        )

        with patch.object(local_status, "run_command", return_value=completed):
            result = collect_podman_status(Path.cwd(), 1, skip_podman=False)

        self.assertEqual(result.status, "warn")
        self.assertEqual(result.data["unhealthy"][0]["name"], "omnicare-dashboard")

    def test_run_status_dry_run_does_not_write_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_file = Path(temp_dir) / "status.json"

            exit_code, report = run_status(
                root=Path(__file__).resolve().parents[2],
                report_file=report_file,
                connect_url="http://connect",
                dashboard_url="http://dashboard",
                timeout_seconds=1,
                skip_podman=True,
                extra_connectors=("oracle-erp-local",),
                dry_run=True,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "planned")
        self.assertIn("oracle-erp-local", report["connectors"])
        self.assertFalse(report_file.exists())

    def test_run_status_writes_report(self) -> None:
        checks = [
            local_status.StatusCheck("podman_containers", "skipped", "skip"),
            local_status.StatusCheck("kafka_connect", "pass", "running"),
            local_status.StatusCheck("dashboard_quality", "pass", "overallStatus=pass"),
            local_status.StatusCheck("local_endpoints", "warn", "grafana unavailable"),
            local_status.StatusCheck("artifacts", "warn", "missing artifacts"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            report_file = Path(temp_dir) / "status.json"
            with patch.object(
                local_status,
                "collect_podman_status",
                return_value=checks[0],
            ), patch.object(
                local_status,
                "collect_connector_status",
                return_value=checks[1],
            ), patch.object(
                local_status,
                "collect_dashboard_quality",
                return_value=checks[2],
            ), patch.object(
                local_status,
                "collect_endpoint_status",
                return_value=checks[3],
            ), patch.object(
                local_status,
                "collect_artifact_status",
                return_value=checks[4],
            ):
                exit_code, report = run_status(
                    root=Path(__file__).resolve().parents[2],
                    report_file=report_file,
                    connect_url="http://connect",
                    dashboard_url="http://dashboard",
                    timeout_seconds=1,
                    skip_podman=True,
                    extra_connectors=(),
                    dry_run=False,
                )

            stored = json.loads(report_file.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "warn")
        self.assertEqual(stored["status"], "warn")


if __name__ == "__main__":
    unittest.main()
