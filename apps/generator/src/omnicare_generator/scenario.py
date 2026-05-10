from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .models import (
    Customer,
    Invoice,
    Order,
    OrderItem,
    Payment,
    Product,
    Refund,
    StockMovement,
    SupportTicket,
)
from .repositories import (
    BillingRepository,
    EngagementRepository,
    InventoryRepository,
    OrderRepository,
)


HOSPITALS = (
    "Central Hospital",
    "Atlas Medical Center",
    "Riverside Clinic",
    "NorthStar Health",
    "Green Valley Hospital",
)
PRODUCT_CATALOG = (
    Product("P-VENT-100", "VENT-100", "ICU Ventilator Kit", "critical_care", "SUP-MED-01"),
    Product("P-SYR-010", "SYR-010", "Sterile Syringe Pack", "consumables", "SUP-MED-02"),
    Product("P-MASK-200", "MASK-200", "Respirator Mask Box", "ppe", "SUP-MED-03"),
    Product("P-PUMP-300", "PUMP-300", "Infusion Pump", "devices", "SUP-MED-01"),
    Product("P-GLOVE-050", "GLOVE-050", "Nitrile Glove Case", "ppe", "SUP-MED-04"),
)


@dataclass(frozen=True)
class ScenarioMix:
    failure_rate: float = 0.12
    refund_rate: float = 0.06
    sla_breach_rate: float = 0.08

    def __post_init__(self) -> None:
        for name, value in (
            ("failure_rate", self.failure_rate),
            ("refund_rate", self.refund_rate),
            ("sla_breach_rate", self.sla_breach_rate),
        ):
            if value < 0 or value > 1:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass
class DemoScenario:
    orders: OrderRepository
    billing: BillingRepository
    engagement: EngagementRepository
    inventory: InventoryRepository | None = None
    mix: ScenarioMix = field(default_factory=ScenarioMix)
    random_seed: int | None = None

    def __post_init__(self) -> None:
        self._random = random.Random(self.random_seed)

    def run_once(self) -> dict[str, str | None]:
        now = datetime.now(tz=UTC).replace(microsecond=0)
        customer = self._customer()
        product = self._product()
        order = self._order(customer, now)
        item = self._order_item(order, product)
        amount_cents = item.quantity * item.unit_price_cents
        invoice = self._invoice(order, amount_cents, now)
        payment = self._payment(invoice, now)
        refund = self._refund(payment, now)
        ticket = self._support_ticket(customer, now)
        stock_movement = self._stock_movement(product, item, now)

        self.orders.upsert_customer(customer)
        self.orders.insert_order(order)
        self.orders.insert_order_item(item)
        self.billing.insert_invoice(invoice)
        self.billing.insert_payment(payment)
        if refund is not None:
            self.billing.insert_refund(refund)
        self.engagement.insert_ticket(ticket)
        if self.inventory is not None:
            self.inventory.upsert_product(product)
            self.inventory.insert_stock_movement(stock_movement)

        return {
            "customer_id": str(customer.customer_id),
            "order_id": str(order.order_id),
            "order_item_id": str(item.order_item_id),
            "invoice_id": invoice.invoice_id,
            "payment_id": payment.payment_id,
            "refund_id": refund.refund_id if refund is not None else None,
            "ticket_id": ticket.ticket_id,
            "product_id": product.product_id,
            "stock_movement_id": stock_movement.movement_id
            if self.inventory is not None
            else None,
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
            order_status=(
                "backordered"
                if self._chance(self.mix.failure_rate)
                else self._random.choice(("confirmed", "allocated", "shipped"))
            ),
            channel=self._random.choice(("portal", "edi", "sales_rep")),
            ordered_at=now,
        )

    def _product(self) -> Product:
        return self._random.choice(PRODUCT_CATALOG)

    def _order_item(self, order: Order, product: Product) -> OrderItem:
        return OrderItem(
            order_item_id=uuid4(),
            order_id=order.order_id,
            customer_id=order.customer_id,
            product_id=product.product_id,
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
        status = (
            "failed"
            if self._chance(self.mix.failure_rate)
            else self._random.choice(("captured", "captured", "pending"))
        )
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

    def _refund(self, payment: Payment, now: datetime) -> Refund | None:
        if payment.payment_status != "captured" or not self._chance(self.mix.refund_rate):
            return None

        return Refund(
            refund_id=f"REF-{uuid4()}",
            payment_id=payment.payment_id,
            refund_reason=self._random.choice(
                ("duplicate_charge", "returned_goods", "contract_adjustment")
            ),
            amount_cents=max(100, payment.amount_cents // self._random.choice((2, 3, 4))),
            refunded_at=now + timedelta(minutes=self._random.randint(5, 120)),
        )

    def _stock_movement(
        self,
        product: Product,
        item: OrderItem,
        now: datetime,
    ) -> StockMovement:
        if item.order_status in {"confirmed", "allocated", "shipped"}:
            movement_type = "shipment"
            quantity = item.quantity
        else:
            movement_type = self._random.choice(("adjustment_out", "adjustment_in"))
            quantity = self._random.randint(1, 5)

        return StockMovement(
            movement_id=f"MOV-{uuid4()}",
            product_id=product.product_id,
            warehouse_id=self._random.choice(("WH-CASA-01", "WH-RABAT-01", "WH-TANGER-01")),
            movement_type=movement_type,
            quantity=quantity,
            movement_ts=now,
        )

    def _support_ticket(self, customer: Customer, now: datetime) -> SupportTicket:
        breached = self._chance(self.mix.sla_breach_rate)
        status = (
            self._random.choice(("open", "waiting_customer"))
            if breached
            else self._random.choice(("open", "waiting_customer", "resolved"))
        )
        return SupportTicket(
            ticket_id=f"TCK-{uuid4()}",
            customer_id=customer.customer_id,
            priority=(
                self._random.choice(("high", "critical"))
                if breached
                else self._random.choice(("low", "medium", "high", "critical"))
            ),
            status=status,
            opened_at=now,
            sla_due_at=(
                now - timedelta(minutes=self._random.randint(15, 240))
                if breached
                else now + timedelta(hours=self._random.choice((4, 8, 24, 48)))
            ),
            closed_at=now if status == "resolved" else None,
        )

    def _chance(self, probability: float) -> bool:
        return self._random.random() < probability
