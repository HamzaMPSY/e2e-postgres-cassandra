from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Customer:
    customer_id: UUID
    hospital_name: str
    segment: str
    city: str
    country: str


@dataclass(frozen=True)
class Order:
    order_id: UUID
    customer_id: UUID
    order_status: str
    channel: str
    ordered_at: datetime


@dataclass(frozen=True)
class OrderItem:
    order_item_id: UUID
    order_id: UUID
    customer_id: UUID
    product_id: str
    channel: str
    order_status: str
    ordered_at: datetime
    quantity: int
    unit_price_cents: int


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    order_id: UUID
    customer_id: UUID
    invoice_status: str
    amount_cents: int
    issued_at: datetime


@dataclass(frozen=True)
class Payment:
    payment_id: str
    invoice_id: str
    order_id: UUID
    customer_id: UUID
    payment_status: str
    payment_method: str
    amount_cents: int
    paid_at: datetime | None


@dataclass(frozen=True)
class Refund:
    refund_id: str
    payment_id: str
    refund_reason: str
    amount_cents: int
    refunded_at: datetime


@dataclass(frozen=True)
class Product:
    product_id: str
    sku: str
    product_name: str
    product_category: str
    supplier_id: str


@dataclass(frozen=True)
class StockMovement:
    movement_id: str
    product_id: str
    warehouse_id: str
    movement_type: str
    quantity: int
    movement_ts: datetime


@dataclass(frozen=True)
class SupportTicket:
    ticket_id: str
    customer_id: UUID
    priority: str
    status: str
    opened_at: datetime
    sla_due_at: datetime
    closed_at: datetime | None
