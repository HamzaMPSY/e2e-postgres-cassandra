from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")
TOPIC_PREFIX = re.compile(r"^cdc\.local\.omnicare\.(postgres|mysql|mongo|oracle)$")

REQUIRED_ENV_VARS = {
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "MYSQL_DATABASE",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_ROOT_PASSWORD",
    "CASSANDRA_CLUSTER_NAME",
    "CASSANDRA_DC",
    "KAFKA_BOOTSTRAP_SERVERS",
    "KAFKA_SECURITY_PROTOCOL",
    "KAFKA_SASL_MECHANISM",
    "KAFKA_SASL_USERNAME",
    "KAFKA_SASL_PASSWORD",
    "KAFKA_SSL_CA_LOCATION",
    "DEBEZIUM_SIGNAL_TOPIC",
    "CASSANDRA_CONTACT_POINTS",
    "CASSANDRA_KEYSPACE",
    "CASSANDRA_LOCAL_DC",
    "CASSANDRA_PROTOCOL_VERSION",
    "CASSANDRA_USERNAME",
    "CASSANDRA_PASSWORD",
    "CASSANDRA_SSL_CA_CERT",
    "GRAFANA_ADMIN_PASSWORD",
}

REQUIRED_SOURCE_COVERAGE = {
    "public.customers",
    "public.order_items",
    "billing.payments",
    "engagement.support_tickets",
}


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_repo(root: Path) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    env = parse_env_file(root / ".env.example")
    missing_env = sorted(REQUIRED_ENV_VARS - set(env))
    errors.extend(f".env.example missing required variable: {name}" for name in missing_env)

    connector_files = sorted((root / "connectors").glob("*.json"))
    if not connector_files:
        errors.append("No connector JSON files found under connectors/")
        return ValidationResult(errors=errors, warnings=warnings)

    names: set[str] = set()
    captured_sources: set[str] = set()
    signal_group_ids: dict[str, Path] = {}

    for path in connector_files:
        payload = load_json(path, errors)
        if payload is None:
            continue

        name = payload.get("name")
        config = payload.get("config")
        if not isinstance(name, str) or not name:
            errors.append(f"{path}: missing connector name")
            continue
        if name in names:
            errors.append(f"{path}: duplicate connector name {name!r}")
        names.add(name)

        if not isinstance(config, dict):
            errors.append(f"{path}: missing config object")
            continue

        validate_connector(path, config, env, captured_sources, signal_group_ids, errors, warnings)

    missing_sources = sorted(REQUIRED_SOURCE_COVERAGE - captured_sources)
    errors.extend(f"Missing connector source coverage: {source}" for source in missing_sources)

    return ValidationResult(errors=errors, warnings=warnings)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{path}: invalid JSON: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{path}: root value must be an object")
        return None
    return payload


def validate_connector(
    path: Path,
    config: dict[str, Any],
    env: dict[str, str],
    captured_sources: set[str],
    signal_group_ids: dict[str, Path],
    errors: list[str],
    warnings: list[str],
) -> None:
    connector_class = require_string(path, config, "connector.class", errors)
    topic_prefix = require_string(path, config, "topic.prefix", errors)

    if topic_prefix and not TOPIC_PREFIX.match(topic_prefix):
        errors.append(f"{path}: invalid topic.prefix {topic_prefix!r}")

    for placeholder in sorted(placeholders(config)):
        if placeholder not in env:
            errors.append(f"{path}: placeholder ${{{placeholder}}} missing from .env.example")

    if connector_class and "PostgresConnector" in connector_class:
        collect_csv(config, "table.include.list", captured_sources)
        require_string(path, config, "plugin.name", errors)
        require_string(path, config, "publication.name", errors)
        require_string(path, config, "slot.name", errors)
        require_resnapshot_signaling(path, config, "table.include.list", signal_group_ids, errors)
    elif connector_class and "MySqlConnector" in connector_class:
        collect_csv(config, "table.include.list", captured_sources)
        require_string(path, config, "database.server.id", errors)
        require_string(path, config, "schema.history.internal.kafka.topic", errors)
        require_resnapshot_signaling(path, config, "table.include.list", signal_group_ids, errors)
    elif connector_class and "MongoDbConnector" in connector_class:
        collect_csv(config, "collection.include.list", captured_sources)
        require_string(path, config, "mongodb.connection.string", errors)
        require_resnapshot_signaling(
            path, config, "collection.include.list", signal_group_ids, errors
        )
    elif connector_class and "OracleConnector" in connector_class:
        require_resnapshot_signaling(path, config, "table.include.list", signal_group_ids, errors)
        warnings.append(f"{path}: Oracle connector is template-only and not validated locally")
    elif connector_class:
        errors.append(f"{path}: unsupported connector.class {connector_class!r}")


def require_string(
    path: Path,
    config: dict[str, Any],
    key: str,
    errors: list[str],
) -> str | None:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: missing required config {key!r}")
        return None
    return value.strip()


def require_resnapshot_signaling(
    path: Path,
    config: dict[str, Any],
    include_key: str,
    signal_group_ids: dict[str, Path],
    errors: list[str],
) -> None:
    channels = require_string(path, config, "signal.enabled.channels", errors)
    channel_set = {part.strip() for part in channels.split(",")} if channels else set()
    if channels and "source" not in channel_set:
        errors.append(f"{path}: signal.enabled.channels must include 'source'")
    if channels and "kafka" not in channel_set:
        errors.append(f"{path}: signal.enabled.channels must include 'kafka'")
    signal_data_collection = require_string(path, config, "signal.data.collection", errors)
    if signal_data_collection and signal_data_collection not in csv_values(config, include_key):
        errors.append(
            f"{path}: signal.data.collection {signal_data_collection!r} must be listed in {include_key!r}"
        )
    require_string(path, config, "signal.kafka.bootstrap.servers", errors)
    group_id = require_string(path, config, "signal.kafka.groupId", errors)
    if group_id:
        other_path = signal_group_ids.get(group_id)
        if other_path:
            errors.append(
                f"{path}: signal.kafka.groupId {group_id!r} is already used by {other_path}"
            )
        signal_group_ids[group_id] = path
    require_string(path, config, "signal.kafka.topic", errors)


def collect_csv(config: dict[str, Any], key: str, target: set[str]) -> None:
    target.update(csv_values(config, key))


def csv_values(config: dict[str, Any], key: str) -> set[str]:
    value = config.get(key)
    if not isinstance(value, str):
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


def placeholders(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            found.update(placeholders(child))
    elif isinstance(value, list):
        for child in value:
            found.update(placeholders(child))
    elif isinstance(value, str):
        found.update(PLACEHOLDER.findall(value))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to validate.",
    )
    args = parser.parse_args(argv)

    result = validate_repo(args.root)
    for warning in result.warnings:
        print(f"WARN: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if result.ok:
        print("Config validation passed.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
