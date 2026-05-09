from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .models import Customer, Invoice, Order, OrderItem, Payment, SupportTicket
from .repositories import BillingRepository, EngagementRepository, OrderRepository


HOSPITALS = (
    "Central Hospital",
    "Atlas Medical Center",
    "Riverside Clinic",
    "NorthStar Health",
    "Green Valley Hospital",
)
PRODUCTS = ("P-VENT-100", "P-SYR-010", "P-MASK-200", "P-PUMP-300", "P-GLOVE-050")


@dataclass
class DemoScenario:
    orders: OrderRepository
    billing: BillingRepository
    engagement: EngagementRepository
    random_seed: int | None = None

    def __post_init__(self) -> None:
        self._random = random.Random(self.random_seed)

    def run_once(self) -> dict[str, str]:
        now = datetime.now(tz=UTC).replace(microsecond=0)
        customer = self._customer()
        order = self._order(customer, now)
        item = self._order_item(order)
        amount_cents = item.quantity * item.unit_price_cents
        invoice = self._invoice(order, amount_cents, now)
        payment = self._payment(invoice, now)
        ticket = self._support_ticket(customer, now)

        self.orders.upsert_customer(customer)
        self.orders.insert_order(order)
        self.orders.insert_order_item(item)
        self.billing.insert_invoice(invoice)
        self.billing.insert_payment(payment)
        self.engagement.insert_ticket(ticket)

        return {
            "customer_id": str(customer.customer_id),
            "order_id": str(order.order_id),
            "order_item_id": str(item.order_item_id),
            "invoice_id": invoice.invoice_id,
            "payment_id": payment.payment_id,
            "ticket_id": ticket.ticket_id,
        }

    def _customer(self) -> Customer:
        return Customer(
            customer_id=uuid4(),
            hospital_name=self._random.choice(HOSPITALS),
            segment=self._random.choice(("enterprise", "regional", "clinic")),
            city=self._random.choice(("Casablanca", "Rabat", "Marrakesh", "Tangier")),
            country="MA",
        )

    def _order(self, customer: Customer, now: datetime) -> Order:
        return Order(
            order_id=uuid4(),
            customer_id=customer.customer_id,
            order_status=self._random.choice(("confirmed", "allocated", "shipped")),
            channel=self._random.choice(("portal", "edi", "sales_rep")),
            ordered_at=now,
        )

    def _order_item(self, order: Order) -> OrderItem:
        return OrderItem(
            order_item_id=uuid4(),
            order_id=order.order_id,
            customer_id=order.customer_id,
            product_id=self._random.choice(PRODUCTS),
            channel=order.channel,
            order_status=order.order_status,
            ordered_at=order.ordered_at,
            quantity=self._random.randint(1, 12),
            unit_price_cents=self._random.choice((500, 1250, 2500, 7999, 15000)),
        )

    def _invoice(self, order: Order, amount_cents: int, now: datetime) -> Invoice:
        return Invoice(
            invoice_id=f"INV-{uuid4()}",
            order_id=order.order_id,
            customer_id=order.customer_id,
            invoice_status=self._random.choice(("issued", "paid", "overdue")),
            amount_cents=amount_cents,
            issued_at=now,
        )

    def _payment(self, invoice: Invoice, now: datetime) -> Payment:
        status = self._random.choice(("captured", "failed", "pending"))
        return Payment(
            payment_id=f"PAY-{uuid4()}",
            invoice_id=invoice.invoice_id,
            order_id=invoice.order_id,
            customer_id=invoice.customer_id,
            payment_status=status,
            payment_method=self._random.choice(("card", "wire", "insurance")),
            amount_cents=invoice.amount_cents,
            paid_at=now if status == "captured" else None,
        )

    def _support_ticket(self, customer: Customer, now: datetime) -> SupportTicket:
        status = self._random.choice(("open", "waiting_customer", "resolved"))
        return SupportTicket(
            ticket_id=f"TCK-{uuid4()}",
            customer_id=customer.customer_id,
            priority=self._random.choice(("low", "medium", "high", "critical")),
            status=status,
            opened_at=now,
            sla_due_at=now + timedelta(hours=self._random.choice((4, 8, 24, 48))),
            closed_at=now if status == "resolved" else None,
        )
