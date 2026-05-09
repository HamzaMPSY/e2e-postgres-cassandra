from __future__ import annotations

from typing import Any, Protocol

from .models import Customer, Invoice, Order, OrderItem, Payment, SupportTicket


class OrderRepository(Protocol):
    def upsert_customer(self, customer: Customer) -> None: ...
    def insert_order(self, order: Order) -> None: ...
    def insert_order_item(self, item: OrderItem) -> None: ...


class BillingRepository(Protocol):
    def insert_invoice(self, invoice: Invoice) -> None: ...
    def insert_payment(self, payment: Payment) -> None: ...


class EngagementRepository(Protocol):
    def insert_ticket(self, ticket: SupportTicket) -> None: ...


class PsycopgOrderRepository:
    def __init__(self, connection: Any):
        self._connection = connection

    def upsert_customer(self, customer: Customer) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO customers (
                  customer_id, hospital_name, segment, city, country
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (customer_id) DO UPDATE SET
                  hospital_name = EXCLUDED.hospital_name,
                  segment = EXCLUDED.segment,
                  city = EXCLUDED.city,
                  country = EXCLUDED.country,
                  updated_at = now()
                """,
                (
                    customer.customer_id,
                    customer.hospital_name,
                    customer.segment,
                    customer.city,
                    customer.country,
                ),
            )
        self._connection.commit()

    def insert_order(self, order: Order) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO orders (
                  order_id, customer_id, order_status, channel, ordered_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    order.order_id,
                    order.customer_id,
                    order.order_status,
                    order.channel,
                    order.ordered_at,
                ),
            )
        self._connection.commit()

    def insert_order_item(self, item: OrderItem) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO order_items (
                  order_item_id, order_id, customer_id, product_id, channel,
                  order_status, ordered_at, quantity, unit_price_cents
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    item.order_item_id,
                    item.order_id,
                    item.customer_id,
                    item.product_id,
                    item.channel,
                    item.order_status,
                    item.ordered_at,
                    item.quantity,
                    item.unit_price_cents,
                ),
            )
        self._connection.commit()


class PymysqlBillingRepository:
    def __init__(self, connection: Any):
        self._connection = connection

    def insert_invoice(self, invoice: Invoice) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO invoices (
                  invoice_id, order_id, customer_id, invoice_status,
                  amount_cents, issued_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    invoice.invoice_id,
                    str(invoice.order_id),
                    str(invoice.customer_id),
                    invoice.invoice_status,
                    invoice.amount_cents,
                    invoice.issued_at,
                ),
            )
        self._connection.commit()

    def insert_payment(self, payment: Payment) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO payments (
                  payment_id, invoice_id, order_id, customer_id,
                  payment_status, payment_method, amount_cents, paid_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payment.payment_id,
                    payment.invoice_id,
                    str(payment.order_id),
                    str(payment.customer_id),
                    payment.payment_status,
                    payment.payment_method,
                    payment.amount_cents,
                    payment.paid_at,
                ),
            )
        self._connection.commit()


class PymongoEngagementRepository:
    def __init__(self, database: Any):
        self._database = database

    def insert_ticket(self, ticket: SupportTicket) -> None:
        self._database.support_tickets.insert_one(
            {
                "ticket_id": ticket.ticket_id,
                "customer_id": str(ticket.customer_id),
                "priority": ticket.priority,
                "status": ticket.status,
                "opened_at": ticket.opened_at,
                "sla_due_at": ticket.sla_due_at,
                "closed_at": ticket.closed_at,
            }
        )
