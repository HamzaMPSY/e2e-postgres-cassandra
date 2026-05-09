from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from validate_contracts import validate_contracts


class ValidateContractsTest(unittest.TestCase):
    def test_current_repo_contracts_are_valid(self) -> None:
        root = Path(__file__).resolve().parents[2]

        result = validate_contracts(root)

        self.assertEqual(result.errors, [])

    def test_detects_connector_stream_without_source_contract(self) -> None:
        with self._fixture_root() as root:
            contract_path = root / "contracts" / "cdc-data-contracts.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["sourceContracts"] = [
                source
                for source in contract["sourceContracts"]
                if source["sourceId"] != "mysql-billing-payments"
            ]
            contract_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")

            result = validate_contracts(root)

        self.assertTrue(
            any(
                "'billing.payments' has no source contract" in error
                for error in result.errors
            )
        )

    def test_detects_target_contract_column_missing_from_cassandra(self) -> None:
        with self._fixture_root() as root:
            schema_path = root / "cassandra" / "schema.cql"
            schema_path.write_text(
                schema_path.read_text(encoding="utf-8").replace(
                    "  gross_amount_cents bigint,\n", ""
                ),
                encoding="utf-8",
            )

            result = validate_contracts(root)

        self.assertTrue(
            any(
                "fact_order_line_by_day.gross_amount_cents" in error
                for error in result.errors
            )
        )

    def test_detects_materialized_source_without_transformer_mapper(self) -> None:
        with self._fixture_root() as root:
            contract_path = root / "contracts" / "cdc-data-contracts.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["sourceContracts"].append(
                {
                    "sourceId": "postgres-orders-unmapped",
                    "ownerApplication": "orders",
                    "sourceEngine": "postgres",
                    "dataCollection": "public.unmapped_table",
                    "topicPrefixes": ["cdc.local.omnicare.postgres"],
                    "keyFields": ["unmapped_id"],
                    "requiredAfterFields": ["unmapped_id"],
                    "materialization": "fact",
                    "targetTables": ["fact_order_line_by_day"],
                    "piiClassification": ["none"],
                }
            )
            contract_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")

            result = validate_contracts(root)

        self.assertTrue(any("public.unmapped_table" in error for error in result.errors))

    @contextmanager
    def _fixture_root(self) -> Iterator[Path]:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)

            shutil.copytree(root / "contracts", fixture / "contracts")
            shutil.copytree(root / "connectors", fixture / "connectors")
            (fixture / "cassandra").mkdir()
            shutil.copy(
                root / "cassandra" / "schema.cql",
                fixture / "cassandra" / "schema.cql",
            )
            transformer_dir = fixture / "transformer" / "src" / "omnicare_cdc"
            transformer_dir.mkdir(parents=True)
            shutil.copy(
                root / "transformer" / "src" / "omnicare_cdc" / "star_schema.py",
                transformer_dir / "star_schema.py",
            )
            yield fixture


if __name__ == "__main__":
    unittest.main()
