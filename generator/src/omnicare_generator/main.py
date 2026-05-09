from __future__ import annotations

import argparse
import json
import time

from .config import GeneratorConfig
from .repositories import (
    PsycopgOrderRepository,
    PymongoEngagementRepository,
    PymysqlBillingRepository,
)
from .scenario import DemoScenario


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    args = parser.parse_args()

    config = GeneratorConfig.from_env()
    scenario = _scenario(config)

    for _ in range(args.iterations):
        print(json.dumps(scenario.run_once(), sort_keys=True))
        if args.sleep_seconds:
            time.sleep(args.sleep_seconds)


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
    )


if __name__ == "__main__":
    main()
