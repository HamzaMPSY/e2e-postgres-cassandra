from __future__ import annotations

import os
from dataclasses import dataclass


INVENTORY_SOURCE_POSTGRES_FALLBACK = "postgres-fallback"
INVENTORY_SOURCE_NONE = "none"
INVENTORY_SOURCE_ORACLE = "oracle"
INVENTORY_SOURCES = (
    INVENTORY_SOURCE_POSTGRES_FALLBACK,
    INVENTORY_SOURCE_NONE,
    INVENTORY_SOURCE_ORACLE,
)


@dataclass(frozen=True)
class GeneratorConfig:
    postgres_dsn: str
    mysql_host: str
    mysql_port: int
    mysql_database: str
    mysql_user: str
    mysql_password: str
    mongo_uri: str
    random_seed: int | None
    failure_rate: float
    refund_rate: float
    sla_breach_rate: float
    inventory_source: str

    @classmethod
    def from_env(cls) -> GeneratorConfig:
        inventory_source = os.environ.get(
            "GENERATOR_INVENTORY_SOURCE",
            INVENTORY_SOURCE_POSTGRES_FALLBACK,
        ).strip()
        if inventory_source not in INVENTORY_SOURCES:
            valid = ", ".join(INVENTORY_SOURCES)
            raise ValueError(f"GENERATOR_INVENTORY_SOURCE must be one of: {valid}")

        return cls(
            postgres_dsn=os.environ.get(
                "POSTGRES_DSN",
                "postgresql://orders_cdc_demo:change_me_orders@localhost:15432/orders",
            ),
            mysql_host=os.environ.get("MYSQL_HOST", "localhost"),
            mysql_port=int(os.environ.get("MYSQL_PORT", "13306")),
            mysql_database=os.environ.get("MYSQL_DATABASE", "billing"),
            mysql_user=os.environ.get("MYSQL_USER", "billing_cdc_demo"),
            mysql_password=os.environ.get("MYSQL_PASSWORD", "change_me_billing"),
            mongo_uri=os.environ.get(
                "MONGO_URI",
                "mongodb://localhost:27017/engagement?directConnection=true",
            ),
            random_seed=_optional_int("GENERATOR_RANDOM_SEED"),
            failure_rate=_probability("GENERATOR_FAILURE_RATE", 0.12),
            refund_rate=_probability("GENERATOR_REFUND_RATE", 0.06),
            sla_breach_rate=_probability("GENERATOR_SLA_BREACH_RATE", 0.08),
            inventory_source=inventory_source,
        )


@dataclass(frozen=True)
class RunConfig:
    iterations: int
    max_events: int
    duration_seconds: float
    rate_per_second: float
    sleep_seconds: float

    @classmethod
    def from_env(cls) -> RunConfig:
        return cls(
            iterations=_non_negative_int("GENERATOR_ITERATIONS", 1),
            max_events=_non_negative_int("GENERATOR_MAX_EVENTS", 0),
            duration_seconds=_non_negative_float("GENERATOR_DURATION_SECONDS", 0.0),
            rate_per_second=_non_negative_float("GENERATOR_RATE_PER_SECOND", 0.0),
            sleep_seconds=_non_negative_float("GENERATOR_SLEEP_SECONDS", 0.0),
        )

    def event_limit(self) -> int:
        if self.max_events > 0:
            return self.max_events
        return self.iterations

    def event_interval_seconds(self) -> float:
        if self.rate_per_second > 0:
            return 1 / self.rate_per_second
        return self.sleep_seconds


def _optional_int(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return int(value)


def _non_negative_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to 0")
    return value


def _non_negative_float(name: str, default: float) -> float:
    value = float(os.environ.get(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to 0")
    return value


def _probability(name: str, default: float) -> float:
    value = _non_negative_float(name, default)
    if value > 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return value
