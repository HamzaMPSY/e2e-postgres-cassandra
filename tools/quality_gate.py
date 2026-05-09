from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def load_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    if args.snapshot_file:
        payload = json.loads(Path(args.snapshot_file).read_text(encoding="utf-8"))
    else:
        request = Request(f"{args.dashboard_url.rstrip('/')}/api/dashboard")
        with urlopen(request, timeout=args.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("dashboard snapshot must be a JSON object")
    return payload


def evaluate_snapshot(
    payload: dict[str, Any],
    *,
    max_snapshot_age_seconds: int,
    allow_warnings: bool,
) -> list[str]:
    failures: list[str] = []
    generated_at = payload.get("generatedAt")
    if not isinstance(generated_at, int | float):
        failures.append("snapshot missing numeric generatedAt")
    else:
        age_seconds = int(time.time() - generated_at)
        if age_seconds > max_snapshot_age_seconds:
            failures.append(
                f"snapshot is stale: ageSeconds={age_seconds}, max={max_snapshot_age_seconds}"
            )

    data_quality = payload.get("dataQuality")
    if not isinstance(data_quality, dict):
        failures.append("snapshot missing dataQuality report")
        return failures

    overall = str(data_quality.get("overallStatus") or "unknown")
    if overall == "fail":
        failures.append("dataQuality overallStatus=fail")
    if overall == "warn" and not allow_warnings:
        failures.append("dataQuality overallStatus=warn")
    if overall not in {"pass", "warn", "fail"}:
        failures.append(f"dataQuality overallStatus is invalid: {overall}")

    checks = data_quality.get("checks")
    if not isinstance(checks, list) or not checks:
        failures.append("dataQuality checks must be a non-empty list")
        return failures
    for check in checks:
        if not isinstance(check, dict):
            failures.append("dataQuality check entries must be objects")
            continue
        name = check.get("name") or "unknown"
        status = check.get("status")
        if status == "fail":
            failures.append(f"quality check failed: {name}")
        elif status == "warn" and not allow_warnings:
            failures.append(f"quality check warning: {name}")
        elif status not in {"pass", "warn", "fail"}:
            failures.append(f"quality check has invalid status: {name}={status}")

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot-file")
    source.add_argument("--dashboard-url")
    parser.add_argument("--timeout-seconds", type=int, default=8)
    parser.add_argument("--max-snapshot-age-seconds", type=int, default=300)
    parser.add_argument("--allow-warnings", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = load_snapshot(args)
        failures = evaluate_snapshot(
            payload,
            max_snapshot_age_seconds=args.max_snapshot_age_seconds,
            allow_warnings=args.allow_warnings,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for failure in failures:
        print(f"ERROR: {failure}", file=sys.stderr)
    if failures:
        return 1
    print("Data quality gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
