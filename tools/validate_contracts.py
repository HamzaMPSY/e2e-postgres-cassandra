from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path("contracts/cdc-data-contracts.json")
CONNECTOR_IGNORE_SUFFIXES = {
    ".debezium_signal",
}
VALID_SOURCE_ENGINES = {"postgres", "mysql", "mongo", "oracle"}
VALID_MATERIALIZATIONS = {"dimension", "fact", "captured-only"}
VALID_COMPATIBILITY_MODES = {
    "BACKWARD",
    "BACKWARD_TRANSITIVE",
    "FULL",
    "FULL_TRANSITIVE",
}
VALID_OPERATIONS = {"c", "r", "u", "d"}
TOPIC_PREFIX = re.compile(r"^cdc\.(local|prod)\.omnicare\.(postgres|mysql|mongo|oracle)$")
CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+omnicare_dashboard\.([a-zA-Z0-9_]+)\s*\((.*?)\)\s*(?:WITH|;)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_contracts(root: Path) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    contract = load_json(root / CONTRACT_PATH, errors)
    if contract is None:
        return ValidationResult(errors=errors, warnings=warnings)

    source_contracts = require_list(contract, "sourceContracts", str(CONTRACT_PATH), errors)
    target_contracts = require_list(contract, "targetContracts", str(CONTRACT_PATH), errors)

    compatibility = contract.get("compatibilityMode")
    if compatibility not in VALID_COMPATIBILITY_MODES:
        errors.append(
            f"{CONTRACT_PATH}: compatibilityMode must be one of {sorted(VALID_COMPATIBILITY_MODES)}"
        )

    event_envelope = contract.get("eventEnvelope")
    if not isinstance(event_envelope, dict):
        errors.append(f"{CONTRACT_PATH}: eventEnvelope must be an object")
    else:
        operations = set(event_envelope.get("allowedOperations") or [])
        if not operations or not operations <= VALID_OPERATIONS:
            errors.append(
                f"{CONTRACT_PATH}: eventEnvelope.allowedOperations must be a non-empty subset of {sorted(VALID_OPERATIONS)}"
            )

    connector_collections = connector_data_collections(root, errors)
    cassandra_tables = parse_cassandra_tables(root / "cassandra" / "schema.cql", errors)
    mapper_tables = parse_transformer_mapper_tables(
        root / "transformer" / "src" / "omnicare_cdc" / "star_schema.py", errors
    )

    target_names = validate_target_contracts(target_contracts, cassandra_tables, errors)
    validate_source_contracts(
        source_contracts,
        target_names,
        connector_collections,
        mapper_tables,
        errors,
        warnings,
    )

    return ValidationResult(errors=errors, warnings=warnings)


def load_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"Missing data contract file: {path}")
        return None
    except json.JSONDecodeError as exc:
        errors.append(f"{path}: invalid JSON: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{path}: root value must be an object")
        return None
    return payload


def require_list(
    payload: dict[str, Any], key: str, context: str, errors: list[str]
) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        errors.append(f"{context}: {key} must be a non-empty list")
        return []
    return value


def validate_target_contracts(
    target_contracts: list[Any],
    cassandra_tables: dict[str, set[str]],
    errors: list[str],
) -> set[str]:
    target_names: set[str] = set()
    for index, raw_contract in enumerate(target_contracts):
        context = f"{CONTRACT_PATH}: targetContracts[{index}]"
        if not isinstance(raw_contract, dict):
            errors.append(f"{context}: must be an object")
            continue
        table = require_string(raw_contract, "table", context, errors)
        if not table:
            continue
        if table in target_names:
            errors.append(f"{context}: duplicate target table {table!r}")
        target_names.add(table)

        table_type = raw_contract.get("tableType")
        if table_type not in {"dimension", "fact"}:
            errors.append(f"{context}: tableType must be 'dimension' or 'fact'")

        required_columns = require_string_list(raw_contract, "requiredColumns", context, errors)
        primary_key = require_string_list(raw_contract, "primaryKey", context, errors)

        actual_columns = cassandra_tables.get(table)
        if actual_columns is None:
            errors.append(f"{context}: target table {table!r} is missing from cassandra/schema.cql")
            continue

        missing_columns = sorted(set(required_columns) - actual_columns)
        for column in missing_columns:
            errors.append(f"{context}: required column {table}.{column} is missing from Cassandra")

        for column in primary_key:
            if column not in required_columns:
                errors.append(f"{context}: primary key column {column!r} must be required")
            if column not in actual_columns:
                errors.append(f"{context}: primary key column {column!r} is missing from Cassandra")

    return target_names


def validate_source_contracts(
    source_contracts: list[Any],
    target_names: set[str],
    connector_collections: set[str],
    mapper_tables: set[str],
    errors: list[str],
    warnings: list[str],
) -> None:
    source_ids: set[str] = set()
    contracted_collections: set[str] = set()
    materialized_target_names: set[str] = set()

    for index, raw_contract in enumerate(source_contracts):
        context = f"{CONTRACT_PATH}: sourceContracts[{index}]"
        if not isinstance(raw_contract, dict):
            errors.append(f"{context}: must be an object")
            continue

        source_id = require_string(raw_contract, "sourceId", context, errors)
        if source_id:
            if source_id in source_ids:
                errors.append(f"{context}: duplicate sourceId {source_id!r}")
            source_ids.add(source_id)

        source_engine = raw_contract.get("sourceEngine")
        if source_engine not in VALID_SOURCE_ENGINES:
            errors.append(f"{context}: sourceEngine must be one of {sorted(VALID_SOURCE_ENGINES)}")

        data_collection = require_string(raw_contract, "dataCollection", context, errors)
        if data_collection:
            contracted_collections.add(normalize_collection(data_collection))
            if "." not in data_collection:
                errors.append(f"{context}: dataCollection must include schema/database and table")

        key_fields = require_string_list(raw_contract, "keyFields", context, errors)
        required_after_fields = require_string_list(
            raw_contract, "requiredAfterFields", context, errors
        )
        missing_keys = sorted(set(key_fields) - set(required_after_fields))
        for field in missing_keys:
            errors.append(f"{context}: key field {field!r} must be listed in requiredAfterFields")

        topic_prefixes = require_string_list(raw_contract, "topicPrefixes", context, errors)
        for prefix in topic_prefixes:
            if not TOPIC_PREFIX.match(prefix):
                errors.append(f"{context}: invalid topic prefix {prefix!r}")

        materialization = raw_contract.get("materialization")
        if materialization not in VALID_MATERIALIZATIONS:
            errors.append(
                f"{context}: materialization must be one of {sorted(VALID_MATERIALIZATIONS)}"
            )

        target_tables = raw_contract.get("targetTables")
        if not isinstance(target_tables, list):
            errors.append(f"{context}: targetTables must be a list")
            target_tables = []
        if materialization == "captured-only" and target_tables:
            errors.append(f"{context}: captured-only sources must not declare targetTables")
        if materialization != "captured-only" and not target_tables:
            errors.append(f"{context}: materialized sources must declare at least one targetTable")

        for table in target_tables:
            if not isinstance(table, str) or not table:
                errors.append(f"{context}: targetTables entries must be non-empty strings")
                continue
            materialized_target_names.add(table)
            if table not in target_names:
                errors.append(f"{context}: target table {table!r} has no target contract")

        if materialization != "captured-only" and data_collection:
            table_name = data_collection.rsplit(".", 1)[-1].lower()
            if table_name not in mapper_tables:
                errors.append(
                    f"{context}: materialized collection {data_collection!r} is not mapped by transformer _MAPPERS"
                )

        pii_classification = raw_contract.get("piiClassification")
        if not isinstance(pii_classification, list) or not pii_classification:
            errors.append(f"{context}: piiClassification must be a non-empty list")

    missing_contracts = sorted(connector_collections - contracted_collections)
    for collection in missing_contracts:
        errors.append(f"{CONTRACT_PATH}: connector collection {collection!r} has no source contract")

    missing_connector_coverage = sorted(contracted_collections - connector_collections)
    for collection in missing_connector_coverage:
        warnings.append(
            f"{CONTRACT_PATH}: source contract {collection!r} is not currently captured by a connector"
        )

    unused_targets = sorted(target_names - materialized_target_names)
    for table in unused_targets:
        errors.append(f"{CONTRACT_PATH}: target contract {table!r} is not used by any source")


def require_string(
    payload: dict[str, Any], key: str, context: str, errors: list[str]
) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{context}: {key} must be a non-empty string")
        return None
    return value.strip()


def require_string_list(
    payload: dict[str, Any], key: str, context: str, errors: list[str]
) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        errors.append(f"{context}: {key} must be a non-empty list")
        return []
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{context}: {key} entries must be non-empty strings")
            continue
        strings.append(item.strip())
    return strings


def connector_data_collections(root: Path, errors: list[str]) -> set[str]:
    connectors_root = root / "connectors"
    collections: set[str] = set()
    if not connectors_root.exists():
        errors.append("Missing connectors/ directory")
        return collections

    for path in sorted(connectors_root.rglob("*.json")):
        payload = load_json(path, errors)
        if payload is None:
            continue
        config = payload.get("config")
        if not isinstance(config, dict):
            errors.append(f"{path}: missing config object")
            continue
        for key in ("table.include.list", "collection.include.list"):
            for value in csv_values(config.get(key)):
                normalized = normalize_collection(value)
                if any(normalized.endswith(suffix) for suffix in CONNECTOR_IGNORE_SUFFIXES):
                    continue
                collections.add(normalized)
    return collections


def csv_values(value: Any) -> set[str]:
    if not isinstance(value, str):
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


def parse_cassandra_tables(path: Path, errors: list[str]) -> dict[str, set[str]]:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"Missing Cassandra schema: {path}")
        return {}

    tables: dict[str, set[str]] = {}
    for match in CREATE_TABLE.finditer(content):
        table = match.group(1)
        body = match.group(2)
        columns: set[str] = set()
        for raw_line in body.splitlines():
            line = raw_line.strip().rstrip(",")
            if not line or line.upper().startswith("PRIMARY KEY"):
                continue
            columns.add(line.split()[0].lower())
        tables[table.lower()] = columns
    return tables


def parse_transformer_mapper_tables(path: Path, errors: list[str]) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"Missing transformer mapper file: {path}")
        return set()
    except SyntaxError as exc:
        errors.append(f"{path}: invalid Python syntax: {exc}")
        return set()

    for node in ast.walk(tree):
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_MAPPERS" for target in node.targets
        ):
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "_MAPPERS":
                value = node.value

        if value is None:
            continue
        if not isinstance(value, ast.Dict):
            errors.append(f"{path}: _MAPPERS must be a dict literal")
            return set()
        mapper_tables: set[str] = set()
        for key in value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                mapper_tables.add(key.value.lower())
            else:
                errors.append(f"{path}: _MAPPERS keys must be string literals")
        return mapper_tables

    errors.append(f"{path}: missing _MAPPERS contract")
    return set()


def normalize_collection(value: str) -> str:
    return value.strip().lower()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    result = validate_contracts(args.root)
    for warning in result.warnings:
        print(f"WARN: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if result.ok:
        print("CDC data contract validation passed.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
