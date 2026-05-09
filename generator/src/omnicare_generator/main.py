from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace

from .config import GeneratorConfig, INVENTORY_SOURCES, RunConfig
from .repositories import (
    PsycopgInventoryRepository,
    PsycopgOrderRepository,
    PymongoEngagementRepository,
    PymysqlBillingRepository,
)
from .scenario import DemoScenario, ScenarioMix


def main() -> None:
    config = GeneratorConfig.from_env()
    run_config = RunConfig.from_env()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--iterations",
        type=_non_negative_int,
        default=run_config.iterations,
        help="Business transactions to generate. 0 means no count limit.",
    )
    parser.add_argument(
        "--max-events",
        type=_non_negative_int,
        default=run_config.max_events,
        help="Upper bound for generated transactions. Overrides --iterations when > 0.",
    )
    parser.add_argument(
        "--duration-seconds",
        type=_non_negative_float,
        default=run_config.duration_seconds,
        help="Stop after this many seconds. 0 disables the time limit.",
    )
    parser.add_argument(
        "--rate-per-second",
        type=_non_negative_float,
        default=run_config.rate_per_second,
        help="Target event rate. Overrides --sleep-seconds when > 0.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=_non_negative_float,
        default=run_config.sleep_seconds,
        help="Delay between events when --rate-per-second is not set.",
    )
    parser.add_argument("--seed", type=int, default=config.random_seed)
    parser.add_argument(
        "--failure-rate",
        type=_probability,
        default=config.failure_rate,
        help="Probability of backordered orders and failed payments.",
    )
    parser.add_argument(
        "--refund-rate",
        type=_probability,
        default=config.refund_rate,
        help="Probability of a refund for a captured payment.",
    )
    parser.add_argument(
        "--sla-breach-rate",
        type=_probability,
        default=config.sla_breach_rate,
        help="Probability of an already-breached support SLA.",
    )
    parser.add_argument(
        "--inventory-source",
        choices=INVENTORY_SOURCES,
        default=config.inventory_source,
        help="Use postgres-fallback for local inventory CDC when Oracle is not running.",
    )
    args = parser.parse_args()

    config = replace(
        config,
        random_seed=args.seed,
        failure_rate=args.failure_rate,
        refund_rate=args.refund_rate,
        sla_breach_rate=args.sla_breach_rate,
        inventory_source=args.inventory_source,
    )
    run_config = RunConfig(
        iterations=args.iterations,
        max_events=args.max_events,
        duration_seconds=args.duration_seconds,
        rate_per_second=args.rate_per_second,
        sleep_seconds=args.sleep_seconds,
    )
    scenario = _scenario(config)

    emitted = 0
    started_at = time.monotonic()
    interval_seconds = run_config.event_interval_seconds()
    while True:
        if _should_stop(run_config, emitted, started_at):
            break

        emitted += 1
        result = scenario.run_once()
        print(json.dumps({"sequence": emitted, **result}, sort_keys=True), flush=True)

        if interval_seconds and not _should_stop(run_config, emitted, started_at):
            time.sleep(interval_seconds)


def _scenario(config: GeneratorConfig) -> DemoScenario:
    import psycopg
    import pymysql
    from pymongo import MongoClient

    postgres = psycopg.connect(config.postgres_dsn)
    mysql = pymysql.connect(
        host=config.mysql_host,
        port=config.mysql_port,
        user=config.mysql_user,
        password=config.mysql_password,
        database=config.mysql_database,
        autocommit=False,
    )
    mongo_client = MongoClient(config.mongo_uri)
    mongo_database = mongo_client.get_default_database()

    return DemoScenario(
        orders=PsycopgOrderRepository(postgres),
        billing=PymysqlBillingRepository(mysql),
        engagement=PymongoEngagementRepository(mongo_database),
        inventory=(
            PsycopgInventoryRepository(postgres)
            if config.inventory_source == "postgres-fallback"
            else None
        ),
        mix=ScenarioMix(
            failure_rate=config.failure_rate,
            refund_rate=config.refund_rate,
            sla_breach_rate=config.sla_breach_rate,
        ),
        random_seed=config.random_seed,
    )


def _should_stop(config: RunConfig, emitted: int, started_at: float) -> bool:
    event_limit = config.event_limit()
    if event_limit > 0 and emitted >= event_limit:
        return True
    if config.duration_seconds > 0 and time.monotonic() - started_at >= config.duration_seconds:
        return True
    return False


def _non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return value


def _non_negative_float(raw: str) -> float:
    value = float(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return value


def _probability(raw: str) -> float:
    value = _non_negative_float(raw)
    if value > 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return value


if __name__ == "__main__":
    main()
