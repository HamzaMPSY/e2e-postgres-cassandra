from __future__ import annotations

import unittest
from datetime import UTC, datetime

from omnicare_cdc.cassandra_writer import CassandraStarWriter
from omnicare_cdc.models import StarRow


class FakeSession:
    def __init__(self) -> None:
        self.prepared: list[str] = []
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def prepare(self, query: str) -> str:
        self.prepared.append(query)
        return query

    def execute(self, statement: str, values: tuple[object, ...]) -> None:
        self.executed.append((statement, values))


class CassandraWriterTest(unittest.TestCase):
    def test_writes_star_row_with_prepared_insert(self) -> None:
        session = FakeSession()
        writer = CassandraStarWriter(session=session, keyspace="omnicare_dashboard")
        row = StarRow(
            table="dim_customer_by_id",
            key={"customer_id": "customer-1"},
            values={
                "hospital_name": "Central Hospital",
                "event_ts": datetime(2026, 5, 7, tzinfo=UTC),
                "deleted": False,
            },
        )

        writer.write_row(row)

        self.assertEqual(len(session.prepared), 1)
        self.assertIn(
            "INSERT INTO omnicare_dashboard.dim_customer_by_id",
            session.prepared[0],
        )
        self.assertEqual(len(session.executed), 1)
        self.assertEqual(session.executed[0][1][0], "customer-1")

    def test_rejects_unsafe_table_name(self) -> None:
        session = FakeSession()
        writer = CassandraStarWriter(session=session, keyspace="omnicare_dashboard")

        with self.assertRaises(ValueError):
            writer.write_row(
                StarRow(
                    table="bad;drop",
                    key={"id": "1"},
                    values={},
                )
            )


if __name__ == "__main__":
    unittest.main()

