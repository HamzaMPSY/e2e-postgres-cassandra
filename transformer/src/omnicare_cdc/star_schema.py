from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
from typing import Callable

from .debezium import parse_debezium_event
from .models import JsonMap, SourceEvent, StarRow


Mapper = Callable[[SourceEvent], list[StarRow]]


def to_star_rows(topic: str, value: str | bytes | JsonMap) -> list[StarRow]:
    event = parse_debezium_event(topic, value)
    if event is None:
        return []

    mapper = _MAPPERS.get(event.table)
    if mapper is None:
        return []
    return mapper(event)


def _map_customer(event: SourceEvent) -> list[StarRow]:
    row = event.row
    if row is None:
        return []

    customer_id = str(row["customer_id"])
    return [
        StarRow(
            table="dim_customer_by_id",
            key={"customer_id": customer_id},
            values={
                "hospital_name": row.get("hospital_name"),
                "segment": row.get("segment"),
                "city": row.get("city"),
                "country": row.get("country"),
                "source_topic": event.topic,
                "source_position": event.source_position,
                "event_ts": event.event_datetime,
                "deleted": event.op == "d",
            },
        )
    ]


def _map_order_item(event: SourceEvent) -> list[StarRow]:
    row = event.row
    if row is None:
        return []

    quantity = int(row["quantity"])
    unit_price_cents = int(row["unit_price_cents"])
    event_day = _day(row.get("ordered_at"), event.event_datetime)
    fact_id = _fact_id("order_line", row["order_item_id"], event.source_position)

    return [
        StarRow(
            table="fact_order_line_by_day",
            key={"order_day": event_day, "fact_id": fact_id},
            values={
                "order_id": str(row["order_id"]),
                "order_item_id": str(row["order_item_id"]),
                "customer_id": _optional_str(row.get("customer_id")),
                "product_id": str(row["product_id"]),
                "channel": row.get("channel"),
                "quantity": quantity,
                "unit_price_cents": unit_price_cents,
                "gross_amount_cents": quantity * unit_price_cents,
                "order_status": row.get("order_status"),
                "source_topic": event.topic,
                "source_position": event.source_position,
                "event_ts": event.event_datetime,
                "op": event.op,
            },
        )
    ]


def _map_payment(event: SourceEvent) -> list[StarRow]:
    row = event.row
    if row is None:
        return []

    event_day = _day(row.get("paid_at") or row.get("updated_at"), event.event_datetime)
    fact_id = _fact_id("payment", row["payment_id"], event.source_position)

    return [
        StarRow(
            table="fact_payment_by_day",
            key={"payment_day": event_day, "fact_id": fact_id},
            values={
                "payment_id": str(row["payment_id"]),
                "invoice_id": str(row["invoice_id"]),
                "order_id": _optional_str(row.get("order_id")),
                "customer_id": _optional_str(row.get("customer_id")),
                "payment_status": row.get("payment_status"),
                "payment_method": row.get("payment_method"),
                "amount_cents": int(row["amount_cents"]),
                "source_topic": event.topic,
                "source_position": event.source_position,
                "event_ts": event.event_datetime,
                "op": event.op,
            },
        )
    ]


def _map_refund(event: SourceEvent) -> list[StarRow]:
    row = event.row
    if row is None:
        return []

    event_day = _day(row.get("refunded_at") or row.get("updated_at"), event.event_datetime)
    fact_id = _fact_id("refund", row["refund_id"], event.source_position)

    return [
        StarRow(
            table="fact_refund_by_day",
            key={"refund_day": event_day, "fact_id": fact_id},
            values={
                "refund_id": str(row["refund_id"]),
                "payment_id": str(row["payment_id"]),
                "refund_reason": row.get("refund_reason"),
                "amount_cents": int(row["amount_cents"]),
                "source_topic": event.topic,
                "source_position": event.source_position,
                "event_ts": event.event_datetime,
                "op": event.op,
            },
        )
    ]


def _map_product(event: SourceEvent) -> list[StarRow]:
    row = event.row
    if row is None:
        return []

    return [
        StarRow(
            table="dim_product_by_id",
            key={"product_id": str(row["product_id"])},
            values={
                "sku": row.get("sku"),
                "product_name": row.get("product_name"),
                "product_category": row.get("product_category"),
                "supplier_id": row.get("supplier_id"),
                "source_topic": event.topic,
                "source_position": event.source_position,
                "event_ts": event.event_datetime,
                "deleted": event.op == "d",
            },
        )
    ]


def _map_stock_movement(event: SourceEvent) -> list[StarRow]:
    row = event.row
    if row is None:
        return []

    movement_ts = _datetime(row.get("movement_ts"), event.event_datetime)
    fact_id = _fact_id("inventory", row["movement_id"], event.source_position)

    return [
        StarRow(
            table="fact_inventory_movement_by_product",
            key={
                "product_id": str(row["product_id"]),
                "movement_ts": movement_ts,
                "fact_id": fact_id,
            },
            values={
                "movement_id": str(row["movement_id"]),
                "warehouse_id": str(row["warehouse_id"]),
                "movement_type": row.get("movement_type"),
                "quantity": int(row["quantity"]),
                "source_topic": event.topic,
                "source_position": event.source_position,
                "event_ts": event.event_datetime,
                "op": event.op,
            },
        )
    ]


def _map_support_ticket(event: SourceEvent) -> list[StarRow]:
    row = event.row
    if row is None:
        return []

    opened_at = _datetime(row.get("opened_at"), event.event_datetime)
    fact_id = _fact_id("support", row["ticket_id"], event.source_position)

    return [
        StarRow(
            table="fact_support_case_by_customer",
            key={
                "customer_id": str(row["customer_id"]),
                "opened_day": opened_at.date(),
                "fact_id": fact_id,
            },
            values={
                "ticket_id": str(row["ticket_id"]),
                "priority": row.get("priority"),
                "status": row.get("status"),
                "sla_due_at": _nullable_datetime(row.get("sla_due_at")),
                "closed_at": _nullable_datetime(row.get("closed_at")),
                "source_topic": event.topic,
                "source_position": event.source_position,
                "event_ts": event.event_datetime,
                "op": event.op,
            },
        )
    ]


def _fact_id(prefix: str, natural_id: object, source_position: str) -> str:
    raw = f"{prefix}:{natural_id}:{source_position}"
    return sha256(raw.encode("utf-8")).hexdigest()


def _day(value: object, fallback: datetime) -> date:
    return _datetime(value, fallback).date()


def _datetime(value: object, fallback: datetime) -> datetime:
    parsed = _nullable_datetime(value)
    return parsed if parsed is not None else fallback


def _nullable_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, dict) and "$date" in value:
        date_value = value["$date"]
        if isinstance(date_value, int | float):
            return datetime.fromtimestamp(date_value / 1000)
        return _nullable_datetime(date_value)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Unsupported datetime value: {value!r}")


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


_MAPPERS: dict[str, Mapper] = {
    "customers": _map_customer,
    "order_items": _map_order_item,
    "payments": _map_payment,
    "refunds": _map_refund,
    "products": _map_product,
    "stock_movements": _map_stock_movement,
    "support_tickets": _map_support_ticket,
}
