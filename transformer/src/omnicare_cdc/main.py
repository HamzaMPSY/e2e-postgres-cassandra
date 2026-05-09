from __future__ import annotations

import logging
import argparse

from .cassandra_writer import connect_cassandra
from .config import AppConfig
from .dlq import connect_dlq_producer
from .metrics import MetricsRegistry, start_metrics_server
from .service import TransformerService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-messages",
        type=int,
        default=0,
        help="Process at most this many Kafka messages, then exit. 0 means run forever.",
    )
    parser.add_argument(
        "--idle-timeout-seconds",
        type=float,
        default=10.0,
        help="With --max-messages, exit after this many seconds without a message.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = AppConfig.from_env()
    metrics = MetricsRegistry()
    if config.metrics_enabled:
        start_metrics_server(metrics, host=config.metrics_host, port=config.metrics_port)
        logging.info(
            "Transformer metrics listening on %s:%s",
            config.metrics_host,
            config.metrics_port,
        )

    consumer = _connect_consumer(config)
    writer = connect_cassandra(
        contact_points=config.cassandra_contact_points,
        keyspace=config.cassandra_keyspace,
        local_dc=config.cassandra_local_dc,
        protocol_version=config.cassandra_protocol_version,
        username=config.cassandra_username,
        password=config.cassandra_password,
        ssl_ca_cert=config.cassandra_ssl_ca_cert,
    )
    dlq = connect_dlq_producer(
        bootstrap_servers=config.kafka_bootstrap_servers,
        topic=config.dlq_topic,
        security_config=config.kafka_security_config(),
        include_payloads=config.dlq_include_payloads,
    )
    consumer.subscribe(list(config.source_topics))
    service = TransformerService(consumer=consumer, writer=writer, dlq=dlq, metrics=metrics)
    if args.max_messages > 0:
        processed = service.run_until(
            max_messages=args.max_messages,
            idle_timeout_seconds=args.idle_timeout_seconds,
            poll_timeout_seconds=config.poll_timeout_seconds,
        )
        logging.info("Transformer smoke run completed processed_messages=%s", processed)
        return

    service.run_forever(poll_timeout_seconds=config.poll_timeout_seconds)


def _connect_consumer(config: AppConfig):
    try:
        from confluent_kafka import Consumer
    except ImportError as exc:
        raise RuntimeError("confluent-kafka is required to run the transformer") from exc

    return Consumer(_consumer_settings(config))


def _consumer_settings(config: AppConfig) -> dict[str, object]:
    settings: dict[str, object] = {
        "bootstrap.servers": config.kafka_bootstrap_servers,
        "group.id": config.kafka_group_id,
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
        "isolation.level": "read_committed",
    }
    settings.update(config.kafka_security_config())
    return settings


if __name__ == "__main__":
    main()
