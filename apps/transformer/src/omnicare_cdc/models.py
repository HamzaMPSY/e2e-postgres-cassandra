from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


JsonMap = dict[str, Any]


@dataclass(frozen=True)
class SourceEvent:
    topic: str
    database: str | None
    schema: str | None
    table: str
    op: str
    ts_ms: int | None
    source_position: str
    before: JsonMap | None
    after: JsonMap | None

    @property
    def row(self) -> JsonMap | None:
        if self.op == "d":
            return self.before
        return self.after

    @property
    def event_datetime(self) -> datetime:
        if self.ts_ms is None:
            return datetime.now(tz=UTC)
        return datetime.fromtimestamp(self.ts_ms / 1000, tz=UTC)


@dataclass(frozen=True)
class StarRow:
    table: str
    key: JsonMap
    values: JsonMap

