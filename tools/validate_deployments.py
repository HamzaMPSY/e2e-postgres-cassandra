from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


REQUIRED_FILES = {
    "deployments/README.md",
    "deployments/aws/README.md",
    "deployments/aws/main.tf",
    "deployments/aws/variables.tf",
    "deployments/aws/outputs.tf",
    "deployments/aws/worker.properties",
    "deployments/gcp/README.md",
    "deployments/gcp/main.tf",
    "deployments/gcp/variables.tf",
    "deployments/gcp/outputs.tf",
    "deployments/datacenter/helm/omnicare-cdc/Chart.yaml",
    "deployments/datacenter/helm/omnicare-cdc/values.yaml",
    "deployments/datacenter/helm/omnicare-cdc/templates/strimzi-kafka.yaml",
    "deployments/datacenter/helm/omnicare-cdc/templates/strimzi-connect.yaml",
    "deployments/datacenter/helm/omnicare-cdc/templates/kafka-users.yaml",
    "deployments/datacenter/helm/omnicare-cdc/templates/transformer.yaml",
    "deployments/datacenter/helm/omnicare-cdc/templates/dashboard.yaml",
    "docs/v2/DEPLOYMENT.md",
}

REQUIRED_PATTERNS = {
    "deployments/aws/main.tf": [
        "aws_mskconnect_connector",
        "kafka_cluster_encryption_in_transit",
        "aws_iam_policy",
        "security-controls.json",
    ],
    "deployments/gcp/main.tf": [
        "google_datastream_stream",
        "google_dataflow_flex_template_job",
        "google_secret_manager",
        "security-controls.json",
    ],
    "deployments/datacenter/helm/omnicare-cdc/templates/strimzi-kafka.yaml": [
        "kind: Kafka",
        "kind: KafkaNodePool",
        "authorization:",
        "tls: true",
    ],
    "deployments/datacenter/helm/omnicare-cdc/templates/strimzi-connect.yaml": [
        "kind: KafkaConnect",
        "errors.log.include.messages: false",
        "authentication:",
    ],
    "deployments/datacenter/helm/omnicare-cdc/templates/kafka-users.yaml": [
        "kind: KafkaUser",
        "patternType: prefix",
        "dlq.prod.omnicare.transformer",
    ],
    "docs/v2/DEPLOYMENT.md": [
        "AWS",
        "GCP",
        "Datacenter Kubernetes",
        "deployments/aws",
        "deployments/gcp",
        "deployments/datacenter/helm/omnicare-cdc",
    ],
}


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_deployments(root: Path) -> ValidationResult:
    errors: list[str] = []

    for relative in sorted(REQUIRED_FILES):
        path = root / relative
        if not path.is_file():
            errors.append(f"Missing deployment file: {relative}")

    for relative, patterns in REQUIRED_PATTERNS.items():
        path = root / relative
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern not in content:
                errors.append(f"{relative}: missing required pattern {pattern!r}")

    if (root / "docs" / "v2" / "TICKETS.md").exists():
        errors.append("Committed docs/v2/TICKETS.md should not exist; keep tickets in .tickets/")

    validate_no_unsafe_template_values(root, errors)

    return ValidationResult(errors=errors)


def validate_no_unsafe_template_values(root: Path, errors: list[str]) -> None:
    deployment_root = root / "deployments"
    if not deployment_root.exists():
        return
    for path in sorted(deployment_root.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".tf", ".yaml", ".yml", ".properties"}:
            continue
        relative = path.relative_to(root)
        content = path.read_text(encoding="utf-8")
        if ":latest" in content or " latest" in content:
            errors.append(f"{relative}: do not use floating latest image tags")
        if "0.0.0.0/0" in content:
            errors.append(f"{relative}: do not expose deployment templates to 0.0.0.0/0")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    result = validate_deployments(args.root)
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if result.ok:
        print("Deployment validation passed.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
