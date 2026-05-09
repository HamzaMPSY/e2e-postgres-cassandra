from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SECRET_KEY = re.compile(r"(password|passwd|secret|token|private[_-]?key|credential)", re.I)
ENV_REFERENCE = re.compile(r"^\$\{[A-Z0-9_]+(?::-[^}]*)?}$")
SECRET_REFERENCE = re.compile(r"^(cdc|secret|vault|aws|gcp|projects?)/", re.I)
PLACEHOLDER = re.compile(r"^(change_me_|<from-secret-manager>)", re.I)
HIGH_ENTROPY = re.compile(r"\b(?=[A-Za-z0-9+/]{40,}={0,2}\b)(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[A-Za-z0-9+/]{40,}={0,2}\b")
PY_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)(?:\s*#.*)?$")
JSON_ASSIGNMENT = re.compile(r'^\s*"([^"]+)"\s*:\s*"(.*)"\s*,?\s*$')
ENV_ASSIGNMENT = re.compile(r"^\s*-?\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")
YAML_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*:\s*(.+?)\s*$")
SQL_PASSWORD = re.compile(r"\bPASSWORD\s+['\"]([^'\"]+)['\"]", re.I)

TEXT_EXTENSIONS = {
    ".cql",
    ".env",
    ".example",
    ".js",
    ".json",
    ".properties",
    ".py",
    ".sh",
    ".sql",
    ".txt",
    ".yaml",
    ".yml",
}

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".tickets",
    "__pycache__",
    "venv",
    ".venv",
}


@dataclass(frozen=True)
class CheckResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def check_repo(root: Path) -> CheckResult:
    errors: list[str] = []
    warnings: list[str] = []

    controls = load_json(root / "docs" / "v2" / "security-controls.json", errors)
    if isinstance(controls, dict):
        validate_controls(root, controls, errors)

    validate_connector_configs(root, errors)
    scan_for_committed_secrets(root, errors, warnings)
    return CheckResult(errors=errors, warnings=warnings)


def load_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"Missing required security file: {path}")
        return None
    except json.JSONDecodeError as exc:
        errors.append(f"{path}: invalid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path}: root value must be an object")
        return None
    return value


def validate_controls(root: Path, controls: dict[str, Any], errors: list[str]) -> None:
    validate_transport_policy(controls, errors)
    connectors = controls.get("connectors")
    if not isinstance(connectors, dict):
        errors.append("docs/v2/security-controls.json: missing connectors object")
        return

    connector_names = load_connector_names(root, errors)
    missing = sorted(connector_names - set(connectors))
    for name in missing:
        errors.append(f"docs/v2/security-controls.json: missing connector controls for {name}")

    for name, payload in connectors.items():
        if not isinstance(payload, dict):
            errors.append(f"docs/v2/security-controls.json: connector {name} must be an object")
            continue
        require_non_empty_string(payload, "production_source_user", name, errors)
        require_non_empty_string(payload, "kafka_principal", name, errors)
        require_non_empty_list(payload, "secret_refs", name, errors)
        require_non_empty_list(payload, "least_privilege_grants", name, errors)
        kafka_acls = require_non_empty_list(payload, "kafka_acls", name, errors)
        for index, acl in enumerate(kafka_acls):
            if isinstance(acl, str) and "*" in acl:
                errors.append(f"{name}: kafka_acls[{index}] must use explicit or PREFIXED resources")
        pii_fields = require_list(payload, "pii_fields", name, errors)
        for index, field in enumerate(pii_fields):
            if not isinstance(field, dict):
                errors.append(f"{name}: pii_fields[{index}] must be an object")
                continue
            require_non_empty_string(field, "field", f"{name}.pii_fields[{index}]", errors)
            require_non_empty_string(
                field, "classification", f"{name}.pii_fields[{index}]", errors
            )
            require_non_empty_string(
                field, "masking_rule", f"{name}.pii_fields[{index}]", errors
            )


def validate_transport_policy(controls: dict[str, Any], errors: list[str]) -> None:
    transport_policy = controls.get("transport_policy")
    if not isinstance(transport_policy, dict):
        errors.append("docs/v2/security-controls.json: missing transport_policy object")
        return
    for key in (
        "database_tls_required",
        "kafka_tls_required",
        "schema_registry_tls_required",
        "cassandra_tls_required",
    ):
        if transport_policy.get(key) is not True:
            errors.append(f"docs/v2/security-controls.json: transport_policy.{key} must be true")


def load_connector_names(root: Path, errors: list[str]) -> set[str]:
    names: set[str] = set()
    for path in sorted((root / "connectors").glob("*.json")):
        payload = load_json(path, errors)
        if not isinstance(payload, dict):
            continue
        name = payload.get("name")
        if isinstance(name, str) and name:
            names.add(name)
    return names


def validate_connector_configs(root: Path, errors: list[str]) -> None:
    for path in sorted((root / "connectors").glob("*.json")):
        payload = load_json(path, errors)
        if not isinstance(payload, dict):
            continue
        config = payload.get("config")
        if not isinstance(config, dict):
            continue
        include_messages = str(config.get("errors.log.include.messages", "false")).lower()
        if include_messages == "true":
            errors.append(f"{path}: errors.log.include.messages must not be true")


def require_non_empty_string(
    payload: dict[str, Any], key: str, context: str, errors: list[str]
) -> None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{context}: missing non-empty {key}")


def require_non_empty_list(
    payload: dict[str, Any], key: str, context: str, errors: list[str]
) -> list[Any]:
    value = require_list(payload, key, context, errors)
    if not value:
        errors.append(f"{context}: {key} must not be empty")
    return value


def require_list(
    payload: dict[str, Any], key: str, context: str, errors: list[str]
) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        errors.append(f"{context}: missing list {key}")
        return []
    return value


def scan_for_committed_secrets(root: Path, errors: list[str], warnings: list[str]) -> None:
    for path in iter_text_files(root):
        relative = path.relative_to(root)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if HIGH_ENTROPY.search(line) and not is_allowed_high_entropy_line(line):
                warnings.append(f"{relative}:{line_number}: high-entropy-looking token requires review")
            key, value = parse_assignment(path, line)
            if not key or not SECRET_KEY.search(key):
                continue
            if is_allowed_secret_value(path, value):
                continue
            errors.append(f"{relative}:{line_number}: secret-like value for {key!r} is not externalized")


def iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix in TEXT_EXTENSIONS or path.name == ".env.example":
            files.append(path)
    return files


def parse_assignment(path: Path, line: str) -> tuple[str | None, str]:
    stripped = line.strip().strip(",")
    if not stripped or stripped.startswith("#") or stripped.startswith("//"):
        return None, ""

    if path.suffix == ".py":
        match = PY_ASSIGNMENT.match(line)
        if not match:
            return None, ""
        return match.group(1), normalize_value(match.group(2))

    if path.suffix == ".json":
        match = JSON_ASSIGNMENT.match(line)
        if not match:
            return None, ""
        return match.group(1), normalize_value(match.group(2))

    if path.suffix in {".yaml", ".yml"}:
        env_match = ENV_ASSIGNMENT.match(line)
        if env_match:
            return env_match.group(1), normalize_value(env_match.group(2))
        yaml_match = YAML_ASSIGNMENT.match(line)
        if yaml_match:
            return yaml_match.group(1), normalize_value(yaml_match.group(2))
        return None, ""

    if path.suffix in {".env", ".example", ".properties", ".sh"} or path.name == ".env.example":
        match = ENV_ASSIGNMENT.match(line)
        if not match:
            return None, ""
        return match.group(1), normalize_value(match.group(2))

    if path.suffix == ".sql":
        match = SQL_PASSWORD.search(line)
        if not match:
            return None, ""
        return "password", normalize_value(match.group(1))

    return None, ""


def normalize_value(value: str) -> str:
    return value.strip().strip(",").strip().strip('"').strip("'")


def is_allowed_secret_value(path: Path, value: str) -> bool:
    if not value:
        return True
    if ENV_REFERENCE.match(value):
        return True
    if re.match(r"^\$\{(secret|secrets|vault|aws|gcp):[^}]+}$", value, re.I):
        return True
    if path.suffix == ".py" and value.startswith(
        ("_env(", "os.getenv(", "os.environ.get(", "re.compile(")
    ):
        return True
    if PLACEHOLDER.match(value):
        return True
    if SECRET_REFERENCE.match(value):
        return True
    if path.suffix == ".py" and re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", value):
        return True
    return False


def is_allowed_high_entropy_line(line: str) -> bool:
    return "sha256" in line.lower() or "hash" in line.lower()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    result = check_repo(args.root)
    for warning in result.warnings:
        print(f"WARN: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if result.ok:
        print("Security check passed.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
