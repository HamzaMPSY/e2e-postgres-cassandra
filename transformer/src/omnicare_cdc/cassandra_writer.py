from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .models import StarRow


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class CassandraStarWriter:
    def __init__(self, session: Any, keyspace: str):
        self._session = session
        self._keyspace = _validate_identifier(keyspace)
        self._prepared: dict[tuple[str, tuple[str, ...]], Any] = {}

    def write_rows(self, rows: Iterable[StarRow]) -> int:
        written = 0
        for row in rows:
            self.write_row(row)
            written += 1
        return written

    def write_row(self, row: StarRow) -> None:
        table = _validate_identifier(row.table)
        data = {**row.key, **row.values}
        columns = tuple(data.keys())
        for column in columns:
            _validate_identifier(column)

        statement = self._statement(table, columns)
        self._session.execute(statement, tuple(data[column] for column in columns))

    def _statement(self, table: str, columns: tuple[str, ...]) -> Any:
        cache_key = (table, columns)
        cached = self._prepared.get(cache_key)
        if cached is not None:
            return cached

        column_sql = ", ".join(columns)
        placeholders = ", ".join(["?"] * len(columns))
        query = (
            f"INSERT INTO {self._keyspace}.{table} "
            f"({column_sql}) VALUES ({placeholders})"
        )
        prepared = self._session.prepare(query)
        self._prepared[cache_key] = prepared
        return prepared


def connect_cassandra(
    contact_points: tuple[str, ...],
    keyspace: str,
    local_dc: str,
    protocol_version: int,
) -> CassandraStarWriter:
    try:
        from cassandra.cluster import Cluster
        from cassandra.policies import DCAwareRoundRobinPolicy
    except ImportError as exc:
        raise RuntimeError(
            "cassandra-driver is required to run the transformer service"
        ) from exc

    cluster = Cluster(
        contact_points=list(contact_points),
        load_balancing_policy=DCAwareRoundRobinPolicy(local_dc=local_dc),
        protocol_version=protocol_version,
    )
    session = cluster.connect()
    return CassandraStarWriter(session=session, keyspace=keyspace)


def _validate_identifier(identifier: str) -> str:
    if not _IDENTIFIER.match(identifier):
        raise ValueError(f"Unsafe Cassandra identifier: {identifier!r}")
    return identifier
