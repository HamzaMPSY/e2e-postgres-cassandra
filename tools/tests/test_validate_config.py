from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from validate_config import REQUIRED_ENV_VARS, placeholders, validate_repo


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
                    "table.include.list": "public.customers,public.order_items,billing.payments,engagement.support_tickets"
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


if __name__ == "__main__":
    unittest.main()
