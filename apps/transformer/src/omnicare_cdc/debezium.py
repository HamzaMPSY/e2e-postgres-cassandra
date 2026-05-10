from __future__ import annotations

import json
from typing import Any

from .models import JsonMap, SourceEvent


def parse_debezium_event(topic: str, value: str | bytes | JsonMap) -> SourceEvent | None:
    payload_root = _decode(value)
    payload = payload_root.get("payload", payload_root)

    if payload is None:
        return None

    source = payload.get("source") or {}
    table = source.get("table") or source.get("collection")
    if table is None:
        raise ValueError("Debezium event is missing source table or collection")

    op = payload.get("op") or "u"
    source_position = _source_position(source)

    return SourceEvent(
        topic=topic,
        database=source.get("db") or source.get("database"),
        schema=source.get("schema"),
        table=str(table).lower(),
        op=str(op),
        ts_ms=payload.get("ts_ms") or source.get("ts_ms"),
        source_position=source_position,
        before=_decode_document(payload.get("before")),
        after=_decode_document(payload.get("after")),
    )


def _decode(value: str | bytes | JsonMap) -> JsonMap:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def _decode_document(value: Any) -> JsonMap | None:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _source_position(source: dict[str, Any]) -> str:
    parts = [
        ("lsn", source.get("lsn")),
        ("scn", source.get("scn")),
        ("file", source.get("file")),
        ("pos", source.get("pos")),
        ("rs", source.get("rs_id")),
        ("ord", source.get("ord")),
        ("tx", source.get("txId") or source.get("tx_id")),
    ]
    rendered = [f"{name}:{value}" for name, value in parts if value is not None]
    return "|".join(rendered) if rendered else "unknown"
