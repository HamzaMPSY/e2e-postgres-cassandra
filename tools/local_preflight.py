from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_REPORT_PATH = Path("artifacts/preflight-report.json")
REQUIRED_ENV_KEYS = {
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "MYSQL_DATABASE",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MONGO_INITDB_ROOT_USERNAME",
    "MONGO_INITDB_ROOT_PASSWORD",
    "KAFKA_BOOTSTRAP_SERVERS",
    "DEBEZIUM_SIGNAL_TOPIC",
    "CASSANDRA_KEYSPACE",
    "GRAFANA_ADMIN_PASSWORD",
}
STATIC_VALIDATION_COMMANDS = [
    ["python", "tools/security_check.py"],
    ["python", "tools/validate_config.py"],
    ["python", "tools/validate_contracts.py"],
    ["python", "tools/validate_deployments.py"],
    [
        "bash",
        "-n",
        "scripts/demo-e2e.sh",
        "scripts/anomaly-e2e.sh",
        "scripts/cdc-replay.sh",
        "scripts/request-resnapshot.sh",
        "scripts/connect-connector.sh",
        "scripts/register-connectors.sh",
        "scripts/recover-bad-facts.sh",
        "scripts/local-preflight.sh",
    ],
]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str
    command: list[str] | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }
        if self.command:
            payload["command"] = self.command
        return payload


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def validate_env_file(root: Path, env_file: Path) -> CheckResult:
    path = env_file if env_file.is_absolute() else root / env_file
    if not path.exists():
        return CheckResult(
            name="env_file",
            status="fail",
            detail=f"missing env file: {env_file}; copy .env.example to .env for local runs",
        )
    values = parse_env_file(path)
    missing = sorted(key for key in REQUIRED_ENV_KEYS if not values.get(key))
    if missing:
        return CheckResult(
            name="env_file",
            status="fail",
            detail=f"missing required env keys: {', '.join(missing)}",
        )
    return CheckResult(
        name="env_file",
        status="pass",
        detail=f"{env_file} contains required local demo settings",
    )


def command_availability(skip_podman: bool) -> list[CheckResult]:
    commands = ["bash", "curl", "python", "jq", "envsubst"]
    if not skip_podman:
        commands.append("podman")

    results: list[CheckResult] = []
    for command in commands:
        path = shutil.which(command)
        results.append(
            CheckResult(
                name=f"command:{command}",
                status="pass" if path else "fail",
                detail=path or f"{command} is not installed or not on PATH",
            )
        )
    return results


def run_command(root: Path, name: str, command: list[str]) -> CheckResult:
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return CheckResult(
            name=name,
            status="fail",
            detail=f"command not found: {command[0]}",
            command=command,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name=name,
            status="fail",
            detail="timed out after 60 seconds",
            command=command,
        )

    output = (completed.stdout + completed.stderr).strip()
    detail = output.splitlines()[-1] if output else "ok"
    return CheckResult(
        name=name,
        status="pass" if completed.returncode == 0 else "fail",
        detail=detail[:500],
        command=command,
    )


def planned_checks(env_file: Path, skip_podman: bool) -> list[str]:
    checks = [
        f"validate env file: {env_file}",
        "check local commands: bash, curl, python, jq, envsubst",
        "run static validators and shell syntax checks",
    ]
    if skip_podman:
        checks.append("skip Podman checks")
    else:
        checks.extend(
            [
                "check podman command",
                "run podman version",
                "run podman compose config",
            ]
        )
    return checks


def run_preflight(
    *,
    root: Path,
    env_file: Path,
    report_file: Path,
    skip_podman: bool,
    dry_run: bool,
) -> tuple[int, dict[str, Any]]:
    if dry_run:
        return 0, {
            "generatedAt": int(time.time()),
            "status": "planned",
            "envFile": str(env_file),
            "reportFile": str(report_file),
            "checks": planned_checks(env_file, skip_podman),
        }

    results: list[CheckResult] = [validate_env_file(root, env_file)]
    results.extend(command_availability(skip_podman))

    for index, command in enumerate(STATIC_VALIDATION_COMMANDS, start=1):
        results.append(run_command(root, f"static_validation:{index}", command))

    if skip_podman:
        results.append(
            CheckResult(
                name="podman",
                status="skipped",
                detail="skipped by --skip-podman",
            )
        )
    else:
        results.append(run_command(root, "podman_version", ["podman", "version"]))
        results.append(
            run_command(
                root,
                "podman_compose_config",
                [
                    "podman",
                    "compose",
                    "--env-file",
                    str(env_file),
                    "-f",
                    "docker-compose.yaml",
                    "config",
                ],
            )
        )

    failed = [check for check in results if check.status == "fail"]
    report = {
        "generatedAt": int(time.time()),
        "status": "failed" if failed else "passed",
        "envFile": str(env_file),
        "checks": [check.to_json() for check in results],
    }
    report_path = report_file if report_file.is_absolute() else root / report_file
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return (1 if failed else 0), report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--report-file", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--skip-podman", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    exit_code, report = run_preflight(
        root=args.root.resolve(),
        env_file=args.env_file,
        report_file=args.report_file,
        skip_podman=args.skip_podman,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print("Local preflight dry-run plan:")
        for check in report["checks"]:
            print(f"- {check}")
        return exit_code

    for check in report["checks"]:
        status = check["status"].upper()
        print(f"{status}: {check['name']} - {check['detail']}")
    print(f"Preflight report: {args.report_file}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
