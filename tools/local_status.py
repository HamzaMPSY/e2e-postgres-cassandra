from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_REPORT_PATH = Path("artifacts/status-report.json")
CONNECTORS = (
    "postgres-orders-local",
    "mysql-billing-local",
    "mongo-engagement-local",
)
ARTIFACTS = (
    "artifacts/preflight-report.json",
    "artifacts/demo-report.json",
    "artifacts/anomaly-report.json",
    "artifacts/recovery-report.json",
)
ENDPOINTS = (
    ("dashboard", "http://localhost:18090/health"),
    ("metrics_exporter", "http://localhost:18091/metrics"),
    ("kafka_lag_exporter", "http://localhost:19308/metrics"),
    ("prometheus", "http://localhost:19090/-/healthy"),
    ("grafana", "http://localhost:13000/api/health"),
)


@dataclass(frozen=True)
class StatusCheck:
    name: str
    status: str
    detail: str
    data: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }
        if self.data is not None:
            payload["data"] = self.data
        return payload


def http_json(url: str, timeout_seconds: int) -> Any:
    request = Request(url)
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def http_ok(url: str, timeout_seconds: int) -> bool:
    request = Request(url)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return 200 <= response.status < 500
    except HTTPError as exc:
        return 200 <= exc.code < 500


def run_command(
    command: list[str],
    *,
    root: Path,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def collect_podman_status(root: Path, timeout_seconds: int, skip_podman: bool) -> StatusCheck:
    if skip_podman:
        return StatusCheck("podman_containers", "skipped", "skipped by --skip-podman")
    try:
        completed = run_command(
            [
                "podman",
                "ps",
                "--filter",
                "name=omnicare",
                "--format",
                "{{.Names}}|{{.Status}}",
            ],
            root=root,
            timeout_seconds=timeout_seconds,
        )
    except FileNotFoundError:
        return StatusCheck("podman_containers", "fail", "podman is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        return StatusCheck("podman_containers", "fail", "podman ps timed out")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() or "podman ps failed"
        return StatusCheck("podman_containers", "fail", detail[:500])

    containers: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        if "|" not in line:
            continue
        name, status = line.split("|", 1)
        containers.append({"name": name.strip(), "status": status.strip()})
    if not containers:
        return StatusCheck("podman_containers", "warn", "no omnicare containers are running")
    unhealthy_markers = ("Exited", "Dead", "unhealthy", "health: starting")
    unhealthy = [
        item
        for item in containers
        if any(marker in item["status"] for marker in unhealthy_markers)
    ]
    return StatusCheck(
        "podman_containers",
        "warn" if unhealthy else "pass",
        f"{len(containers)} omnicare containers visible",
        {"containers": containers, "unhealthy": unhealthy},
    )


def collect_connector_status(
    connect_url: str,
    timeout_seconds: int,
    connectors: tuple[str, ...],
) -> StatusCheck:
    try:
        available = http_json(f"{connect_url.rstrip('/')}/connectors", timeout_seconds)
    except Exception as exc:
        return StatusCheck("kafka_connect", "fail", f"Kafka Connect unavailable: {exc}")
    if not isinstance(available, list):
        return StatusCheck(
            "kafka_connect",
            "fail",
            "Kafka Connect /connectors did not return a list",
        )

    statuses: dict[str, Any] = {}
    missing: list[str] = []
    not_running: list[str] = []
    for connector in connectors:
        if connector not in available:
            missing.append(connector)
            continue
        try:
            payload = http_json(
                f"{connect_url.rstrip('/')}/connectors/{connector}/status",
                timeout_seconds,
            )
        except Exception as exc:
            statuses[connector] = {"error": str(exc)}
            not_running.append(connector)
            continue
        statuses[connector] = payload
        connector_state = (
            (payload.get("connector") or {}).get("state")
            if isinstance(payload, dict)
            else None
        )
        task_states = [
            task.get("state")
            for task in (payload.get("tasks") if isinstance(payload, dict) else []) or []
            if isinstance(task, dict)
        ]
        if connector_state != "RUNNING" or any(state != "RUNNING" for state in task_states):
            not_running.append(connector)

    if missing:
        return StatusCheck(
            "kafka_connect",
            "warn",
            f"missing connectors: {', '.join(missing)}",
            {"available": sorted(str(item) for item in available), "statuses": statuses},
        )
    if not_running:
        return StatusCheck(
            "kafka_connect",
            "warn",
            f"connectors not fully running: {', '.join(sorted(set(not_running)))}",
            {"statuses": statuses},
        )
    return StatusCheck(
        "kafka_connect",
        "pass",
        "all local connectors are RUNNING",
        {"statuses": statuses},
    )


def collect_dashboard_quality(dashboard_url: str, timeout_seconds: int) -> StatusCheck:
    try:
        payload = http_json(f"{dashboard_url.rstrip('/')}/api/dashboard", timeout_seconds)
    except Exception as exc:
        return StatusCheck("dashboard_quality", "fail", f"dashboard API unavailable: {exc}")
    data_quality = payload.get("dataQuality") if isinstance(payload, dict) else None
    if not isinstance(data_quality, dict):
        return StatusCheck("dashboard_quality", "fail", "dashboard response lacks dataQuality")
    overall = str(data_quality.get("overallStatus") or "unknown")
    status = "pass" if overall == "pass" else "warn" if overall == "warn" else "fail"
    failed_checks = [
        str(check.get("name"))
        for check in data_quality.get("checks", [])
        if isinstance(check, dict) and check.get("status") == "fail"
    ]
    detail = f"overallStatus={overall}"
    if failed_checks:
        detail += f"; failed checks: {', '.join(failed_checks)}"
    return StatusCheck(
        "dashboard_quality",
        status,
        detail,
        {
            "summary": payload.get("summary", {}),
            "dataQuality": data_quality,
            "generatedAt": payload.get("generatedAt"),
        },
    )


def collect_endpoint_status(timeout_seconds: int) -> StatusCheck:
    endpoints: list[dict[str, str]] = []
    unavailable: list[str] = []
    for name, url in ENDPOINTS:
        try:
            ok = http_ok(url, timeout_seconds)
        except (URLError, TimeoutError, OSError) as exc:
            endpoints.append({"name": name, "url": url, "status": "fail", "detail": str(exc)})
            unavailable.append(name)
            continue
        endpoints.append(
            {
                "name": name,
                "url": url,
                "status": "pass" if ok else "warn",
                "detail": "reachable",
            }
        )
    return StatusCheck(
        "local_endpoints",
        "warn" if unavailable else "pass",
        (
            "unavailable endpoints: " + ", ".join(unavailable)
            if unavailable
            else "all local endpoints reachable"
        ),
        {"endpoints": endpoints},
    )


def collect_artifact_status(root: Path) -> StatusCheck:
    artifacts: list[dict[str, Any]] = []
    missing: list[str] = []
    for relative in ARTIFACTS:
        path = root / relative
        if not path.exists():
            artifacts.append({"path": relative, "status": "missing"})
            missing.append(relative)
            continue
        stat = path.stat()
        artifacts.append(
            {
                "path": relative,
                "status": "present",
                "sizeBytes": stat.st_size,
                "modifiedAt": int(stat.st_mtime),
            }
        )
    return StatusCheck(
        "artifacts",
        "warn" if missing else "pass",
        "missing artifacts: " + ", ".join(missing) if missing else "all standard artifacts exist",
        {"artifacts": artifacts},
    )


def planned_checks(skip_podman: bool) -> list[str]:
    checks = [
        "check local Podman containers" if not skip_podman else "skip Podman containers",
        "check Kafka Connect connector states",
        "check dashboard data quality",
        "check local dashboard/metrics/Prometheus/Grafana endpoints",
        "check latest local artifact files",
        "write artifacts/status-report.json",
    ]
    return checks


def run_status(
    *,
    root: Path,
    report_file: Path,
    connect_url: str,
    dashboard_url: str,
    timeout_seconds: int,
    skip_podman: bool,
    extra_connectors: tuple[str, ...],
    dry_run: bool,
) -> tuple[int, dict[str, Any]]:
    connectors = tuple(dict.fromkeys((*CONNECTORS, *extra_connectors)))
    if dry_run:
        return 0, {
            "generatedAt": int(time.time()),
            "status": "planned",
            "checks": planned_checks(skip_podman),
            "connectors": list(connectors),
            "reportFile": str(report_file),
        }

    checks = [
        collect_podman_status(root, timeout_seconds, skip_podman),
        collect_connector_status(connect_url, timeout_seconds, connectors),
        collect_dashboard_quality(dashboard_url, timeout_seconds),
        collect_endpoint_status(timeout_seconds),
        collect_artifact_status(root),
    ]
    failed = [check for check in checks if check.status == "fail"]
    warnings = [check for check in checks if check.status == "warn"]
    overall = "failed" if failed else "warn" if warnings else "passed"
    report = {
        "generatedAt": int(time.time()),
        "status": overall,
        "dashboardUrl": dashboard_url,
        "connectUrl": connect_url,
        "checks": [check.to_json() for check in checks],
    }
    path = report_file if report_file.is_absolute() else root / report_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return (1 if failed else 0), report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report-file", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--connect-url", default="http://localhost:18083")
    parser.add_argument("--dashboard-url", default="http://localhost:18090")
    parser.add_argument("--timeout-seconds", type=int, default=5)
    parser.add_argument("--skip-podman", action="store_true")
    parser.add_argument(
        "--extra-connector",
        action="append",
        default=[],
        help="Additional Kafka Connect connector name to check, e.g. oracle-erp-local.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    exit_code, report = run_status(
        root=args.root.resolve(),
        report_file=args.report_file,
        connect_url=args.connect_url,
        dashboard_url=args.dashboard_url,
        timeout_seconds=args.timeout_seconds,
        skip_podman=args.skip_podman,
        extra_connectors=tuple(args.extra_connector),
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print("Local status dry-run plan:")
        print(f"Connectors: {', '.join(report['connectors'])}")
        for check in report["checks"]:
            print(f"- {check}")
        return exit_code

    for check in report["checks"]:
        print(f"{check['status'].upper()}: {check['name']} - {check['detail']}")
    print(f"Local status report: {args.report_file}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
