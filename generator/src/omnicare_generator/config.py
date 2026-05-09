from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratorConfig:
    postgres_dsn: str
    mysql_host: str
    mysql_port: int
    mysql_database: str
    mysql_user: str
    mysql_password: str
    mongo_uri: str

    @classmethod
    def from_env(cls) -> GeneratorConfig:
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
        )
