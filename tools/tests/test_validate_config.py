from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from validate_config import (
    REQUIRED_ENV_VARS,
    has_config_provider_reference,
    placeholders,
    validate_repo,
)


class ValidateConfigTest(unittest.TestCase):
    def test_current_repo_is_valid(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = validate_repo(root)

        self.assertEqual(result.errors, [])

    def test_detects_missing_env_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "connectors").mkdir()
            (root / ".env.example").write_text(
                "\n".join(f"{name}=value" for name in REQUIRED_ENV_VARS - {"POSTGRES_USER"}),
                encoding="utf-8",
            )
            (root / "connectors" / "postgres.json").write_text(
                """
                {
                  "name": "postgres-orders-local",
                  "config": {
                    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
                    "plugin.name": "pgoutput",
                    "database.user": "${POSTGRES_USER}",
                    "topic.prefix": "cdc.local.omnicare.postgres",
                    "publication.name": "dbz_omnicare_orders",
                    "slot.name": "dbz_omnicare_orders",
                    "signal.enabled.channels": "source,kafka",
                    "signal.data.collection": "public.debezium_signal",
                    "signal.kafka.bootstrap.servers": "${KAFKA_BOOTSTRAP_SERVERS}",
                    "signal.kafka.groupId": "omnicare-postgres-signals",
                    "signal.kafka.topic": "${DEBEZIUM_SIGNAL_TOPIC}",
                    "table.include.list": "public.customers,public.order_items,billing.payments,engagement.support_tickets,public.debezium_signal"
                  }
                }
                """,
                encoding="utf-8",
            )

            result = validate_repo(root)

        self.assertIn(".env.example missing required variable: POSTGRES_USER", result.errors)
        self.assertTrue(
            any("placeholder ${POSTGRES_USER} missing" in error for error in result.errors)
        )

    def test_extracts_nested_placeholders(self) -> None:
        self.assertEqual(
            placeholders({"a": "${ONE}", "b": ["${TWO}", {"c": "${THREE}"}]}),
            {"ONE", "TWO", "THREE"},
        )

    def test_detects_config_provider_references(self) -> None:
        self.assertTrue(
            has_config_provider_reference(
                {"database.password": "${secrets:cdc/prod/postgres/orders:password}"}
            )
        )
        self.assertFalse(has_config_provider_reference({"database.password": "${PASSWORD}"}))

    def test_rejects_incomplete_production_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "connectors" / "production").mkdir(parents=True)
            (root / ".env.example").write_text(
                "\n".join(f"{name}=value" for name in REQUIRED_ENV_VARS),
                encoding="utf-8",
            )
            (root / "connectors" / "production" / "postgres.json").write_text(
                """
                {
                  "name": "postgres-orders-prod",
                  "config": {
                    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
                    "plugin.name": "pgoutput",
                    "database.user": "${secrets:cdc/prod/postgres/orders:username}",
                    "database.password": "${secrets:cdc/prod/postgres/orders:password}",
                    "topic.prefix": "cdc.prod.omnicare.postgres",
                    "publication.name": "dbz_omnicare_orders",
                    "slot.name": "slot_a",
                    "signal.enabled.channels": "source,kafka",
                    "signal.data.collection": "public.debezium_signal",
                    "signal.kafka.bootstrap.servers": "${secrets:cdc/prod/kafka:bootstrap_servers}",
                    "signal.kafka.groupId": "omnicare-postgres-signals-prod",
                    "signal.kafka.topic": "cdc.prod.omnicare.signals",
                    "table.include.list": "public.customers,public.order_items,public.products,public.stock_movements,billing.payments,billing.refunds,engagement.support_tickets,public.debezium_signal",
                    "errors.tolerance": "none",
                    "errors.log.enable": "true",
                    "errors.log.include.messages": "false"
                  }
                }
                """,
                encoding="utf-8",
            )

            result = validate_repo(root)

        self.assertTrue(
            any("producer.override.security.protocol" in error for error in result.errors)
        )
        self.assertTrue(any("database.sslmode" in error for error in result.errors))

    def test_detects_duplicate_signal_group_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "connectors").mkdir()
            (root / ".env.example").write_text(
                "\n".join(f"{name}=value" for name in REQUIRED_ENV_VARS),
                encoding="utf-8",
            )
            connector_template = """
                {{
                  "name": "{name}",
                  "config": {{
                    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
                    "plugin.name": "pgoutput",
                    "topic.prefix": "cdc.local.omnicare.postgres",
                    "publication.name": "dbz_omnicare_orders",
                    "slot.name": "{slot}",
                    "signal.enabled.channels": "source,kafka",
                    "signal.data.collection": "public.debezium_signal",
                    "signal.kafka.bootstrap.servers": "${{KAFKA_BOOTSTRAP_SERVERS}}",
                    "signal.kafka.groupId": "duplicate-signal-group",
                    "signal.kafka.topic": "${{DEBEZIUM_SIGNAL_TOPIC}}",
                    "table.include.list": "public.customers,public.order_items,billing.payments,engagement.support_tickets,public.debezium_signal"
                  }}
                }}
                """
            (root / "connectors" / "a.json").write_text(
                connector_template.format(name="postgres-a", slot="slot_a"),
                encoding="utf-8",
            )
            (root / "connectors" / "b.json").write_text(
                connector_template.format(name="postgres-b", slot="slot_b"),
                encoding="utf-8",
            )

            result = validate_repo(root)

        self.assertTrue(
            any(
                "signal.kafka.groupId 'duplicate-signal-group' is already used" in error
                for error in result.errors
            )
        )


if __name__ == "__main__":
    unittest.main()
