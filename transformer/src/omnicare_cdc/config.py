from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_TOPICS = (
    "cdc.local.omnicare.postgres.public.customers,"
    "cdc.local.omnicare.postgres.public.order_items,"
    "cdc.local.omnicare.mysql.billing.payments,"
    "cdc.local.omnicare.oracle.ERP_APP.PRODUCTS,"
    "cdc.local.omnicare.oracle.ERP_APP.STOCK_MOVEMENTS,"
    "cdc.local.omnicare.mongo.engagement.support_tickets"
)


@dataclass(frozen=True)
class AppConfig:
    kafka_bootstrap_servers: str
    kafka_group_id: str
    source_topics: tuple[str, ...]
    dlq_topic: str
    cassandra_contact_points: tuple[str, ...]
    cassandra_keyspace: str
    cassandra_local_dc: str
    cassandra_protocol_version: int
    poll_timeout_seconds: float
    metrics_enabled: bool
    metrics_host: str
    metrics_port: int

    @classmethod
    def from_env(cls) -> AppConfig:
        return cls(
            kafka_bootstrap_servers=_env("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"),
            kafka_group_id=_env("KAFKA_GROUP_ID", "omnicare-cdc-transformer"),
            source_topics=_csv("CDC_SOURCE_TOPICS", DEFAULT_TOPICS),
            dlq_topic=_env("DLQ_TOPIC", "dlq.local.omnicare.transformer"),
            cassandra_contact_points=_csv("CASSANDRA_CONTACT_POINTS", "127.0.0.1"),
            cassandra_keyspace=_env("CASSANDRA_KEYSPACE", "omnicare_dashboard"),
            cassandra_local_dc=_env("CASSANDRA_LOCAL_DC", "datacenter1"),
            cassandra_protocol_version=int(_env("CASSANDRA_PROTOCOL_VERSION", "5")),
            poll_timeout_seconds=float(_env("KAFKA_POLL_TIMEOUT_SECONDS", "1.0")),
            metrics_enabled=_bool("TRANSFORMER_METRICS_ENABLED", True),
            metrics_host=_env("TRANSFORMER_METRICS_HOST", "0.0.0.0"),
            metrics_port=int(_env("TRANSFORMER_METRICS_PORT", "8090")),
        )


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _csv(name: str, default: str) -> tuple[str, ...]:
    value = _env(name, default)
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
