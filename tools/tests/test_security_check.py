from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from security_check import check_repo


class SecurityCheckTest(unittest.TestCase):
    def test_current_repo_passes_security_check(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = check_repo(root)

        self.assertEqual(result.errors, [])

    def test_detects_literal_connector_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _minimal_repo(Path(tmp))
            connector = root / "config" / "connectors" / "postgres-orders.json"
            payload = json.loads(connector.read_text(encoding="utf-8"))
            payload["config"]["database.password"] = "not_externalized"
            connector.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            result = check_repo(root)

        self.assertTrue(
            any(
                "database.password" in error and "not externalized" in error
                for error in result.errors
            )
        )

    def test_detects_admin_password_literal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _minimal_repo(Path(tmp))
            (root / "docker-compose.yaml").write_text(
                "services:\n  grafana:\n    environment:\n      GF_SECURITY_ADMIN_PASSWORD: admin\n",
                encoding="utf-8",
            )

            result = check_repo(root)

        self.assertTrue(
            any("GF_SECURITY_ADMIN_PASSWORD" in error for error in result.errors)
        )

    def test_allows_kubernetes_secret_name_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _minimal_repo(Path(tmp))
            (root / "deployment.yaml").write_text(
                "envFrom:\n  - secretRef:\n      name: runtime-secret\n",
                encoding="utf-8",
            )

            result = check_repo(root)

        self.assertEqual(result.errors, [])

    def test_allows_config_provider_class_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _minimal_repo(Path(tmp))
            (root / "worker.properties").write_text(
                "config.providers.secrets.class=io.strimzi.kafka.KubernetesSecretConfigProvider\n",
                encoding="utf-8",
            )

            result = check_repo(root)

        self.assertEqual(result.errors, [])

    def test_detects_literal_secret_in_terraform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _minimal_repo(Path(tmp))
            terraform = root / "main.tf"
            terraform.write_text('database_password = "plain-text-password"\n', encoding="utf-8")

            result = check_repo(root)

        self.assertTrue(any("database_password" in error for error in result.errors))

    def test_requires_connector_security_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _minimal_repo(Path(tmp))
            controls = json.loads(
                (root / "docs" / "v2" / "security-controls.json").read_text(encoding="utf-8")
            )
            controls["connectors"] = {}
            (root / "docs" / "v2" / "security-controls.json").write_text(
                json.dumps(controls),
                encoding="utf-8",
            )

            result = check_repo(root)

        self.assertIn(
            "docs/v2/security-controls.json: missing connector controls for postgres-orders-local",
            result.errors,
        )

    def test_rejects_wildcard_kafka_acl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _minimal_repo(Path(tmp))
            controls_path = root / "docs" / "v2" / "security-controls.json"
            controls = json.loads(controls_path.read_text(encoding="utf-8"))
            controls["connectors"]["postgres-orders-local"]["kafka_acls"] = [
                "WRITE on topic cdc.prod.omnicare.postgres.*"
            ]
            controls_path.write_text(json.dumps(controls), encoding="utf-8")

            result = check_repo(root)

        self.assertIn(
            "postgres-orders-local: kafka_acls[0] must use explicit or PREFIXED resources",
            result.errors,
        )

    def test_rejects_connector_error_message_logging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _minimal_repo(Path(tmp))
            connector = root / "config" / "connectors" / "postgres-orders.json"
            payload = json.loads(connector.read_text(encoding="utf-8"))
            payload["config"]["errors.log.include.messages"] = "true"
            connector.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            result = check_repo(root)

        self.assertTrue(
            any(
                "errors.log.include.messages must not be true" in error
                for error in result.errors
            )
        )

    def test_rejects_production_connector_error_message_logging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _minimal_repo(Path(tmp))
            production_dir = root / "config" / "connectors" / "production"
            production_dir.mkdir()
            connector = production_dir / "postgres-orders.json"
            connector.write_text(
                json.dumps(
                    {
                        "name": "postgres-orders-prod",
                        "config": {"errors.log.include.messages": "true"},
                    }
                ),
                encoding="utf-8",
            )

            result = check_repo(root)

        self.assertTrue(
            any(
                "config/connectors/production/postgres-orders.json" in error
                and "errors.log.include.messages must not be true" in error
                for error in result.errors
            )
        )


def _minimal_repo(root: Path) -> Path:
    (root / "config" / "connectors").mkdir(parents=True)
    (root / "docs" / "v2").mkdir(parents=True)

    (root / "config" / "connectors" / "postgres-orders.json").write_text(
        json.dumps(
            {
                "name": "postgres-orders-local",
                "config": {
                    "database.user": "${POSTGRES_USER}",
                    "database.password": "${POSTGRES_PASSWORD}",
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "docs" / "v2" / "security-controls.json").write_text(
        json.dumps(
            {
                "transport_policy": {
                    "database_tls_required": True,
                    "kafka_tls_required": True,
                    "schema_registry_tls_required": True,
                    "cassandra_tls_required": True,
                },
                "connectors": {
                    "postgres-orders-local": {
                        "production_source_user": "orders_cdc_prod",
                        "kafka_principal": "User:cdc-postgres-orders",
                        "secret_refs": ["cdc/prod/postgres/orders/password"],
                        "least_privilege_grants": ["SELECT ON public.customers"],
                        "kafka_acls": ["WRITE on PREFIXED topic cdc.prod.omnicare.postgres."],
                        "pii_fields": [
                            {
                                "field": "public.customers.customer_id",
                                "classification": "pseudonymous-identifier",
                                "masking_rule": "hash outside demo",
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return root


if __name__ == "__main__":
    unittest.main()
