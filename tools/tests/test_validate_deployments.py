from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from validate_deployments import REQUIRED_FILES, validate_deployments


class ValidateDeploymentsTest(unittest.TestCase):
    def test_current_repo_is_valid(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = validate_deployments(root)

        self.assertEqual(result.errors, [])

    def test_detects_missing_required_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in REQUIRED_FILES - {"deployments/aws/main.tf"}:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder", encoding="utf-8")

            result = validate_deployments(root)

        self.assertIn("Missing deployment file: deployments/aws/main.tf", result.errors)

    def test_rejects_committed_tickets_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in REQUIRED_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder", encoding="utf-8")
            tickets = root / "docs" / "v2" / "TICKETS.md"
            tickets.write_text("should be local-only", encoding="utf-8")

            result = validate_deployments(root)

        self.assertIn(
            "Committed docs/v2/TICKETS.md should not exist; keep tickets in .tickets/",
            result.errors,
        )

    def test_rejects_latest_image_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _minimal_repo(Path(tmp))
            values = root / "deployments" / "datacenter" / "helm" / "omnicare-cdc" / "values.yaml"
            values.write_text("image: registry.example.com/omnicare/transformer:latest", encoding="utf-8")

            result = validate_deployments(root)

        self.assertIn(
            "deployments/datacenter/helm/omnicare-cdc/values.yaml: do not use floating latest image tags",
            result.errors,
        )

    def test_rejects_public_ingress_cidr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _minimal_repo(Path(tmp))
            main = root / "deployments" / "aws" / "main.tf"
            main.write_text(main.read_text(encoding="utf-8") + '\n"0.0.0.0/0"\n', encoding="utf-8")

            result = validate_deployments(root)

        self.assertIn(
            "deployments/aws/main.tf: do not expose deployment templates to 0.0.0.0/0",
            result.errors,
        )


def _minimal_repo(root: Path) -> Path:
    for relative in REQUIRED_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "placeholder"
        if relative in REQUIRED_PATTERNS_FOR_TESTS:
            content = "\n".join(REQUIRED_PATTERNS_FOR_TESTS[relative])
        path.write_text(content, encoding="utf-8")
    return root


REQUIRED_PATTERNS_FOR_TESTS = {
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


if __name__ == "__main__":
    unittest.main()
