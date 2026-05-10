from __future__ import annotations

import unittest

from omnicare_generator.scenario import DemoScenario
from omnicare_generator.scenario import ScenarioMix


class FakeOrders:
    def __init__(self) -> None:
        self.customers = []
        self.orders = []
        self.items = []

    def upsert_customer(self, customer) -> None:
        self.customers.append(customer)

    def insert_order(self, order) -> None:
        self.orders.append(order)

    def insert_order_item(self, item) -> None:
        self.items.append(item)


class FakeBilling:
    def __init__(self) -> None:
        self.invoices = []
        self.payments = []
        self.refunds = []

    def insert_invoice(self, invoice) -> None:
        self.invoices.append(invoice)

    def insert_payment(self, payment) -> None:
        self.payments.append(payment)

    def insert_refund(self, refund) -> None:
        self.refunds.append(refund)


class FakeEngagement:
    def __init__(self) -> None:
        self.tickets = []

    def insert_ticket(self, ticket) -> None:
        self.tickets.append(ticket)


class FakeInventory:
    def __init__(self) -> None:
        self.products = []
        self.movements = []

    def upsert_product(self, product) -> None:
        self.products.append(product)

    def insert_stock_movement(self, movement) -> None:
        self.movements.append(movement)


class DemoScenarioTest(unittest.TestCase):
    def test_generates_coherent_cross_database_records(self) -> None:
        orders = FakeOrders()
        billing = FakeBilling()
        engagement = FakeEngagement()
        scenario = DemoScenario(
            orders=orders,
            billing=billing,
            engagement=engagement,
            random_seed=7,
        )

        result = scenario.run_once()

        self.assertEqual(len(orders.customers), 1)
        self.assertEqual(len(orders.orders), 1)
        self.assertEqual(len(orders.items), 1)
        self.assertEqual(len(billing.invoices), 1)
        self.assertEqual(len(billing.payments), 1)
        self.assertEqual(len(billing.refunds), 0)
        self.assertEqual(len(engagement.tickets), 1)
        self.assertEqual(orders.items[0].order_id, orders.orders[0].order_id)
        self.assertEqual(billing.invoices[0].order_id, orders.orders[0].order_id)
        self.assertEqual(billing.payments[0].order_id, orders.orders[0].order_id)
        self.assertEqual(billing.payments[0].customer_id, orders.customers[0].customer_id)
        self.assertEqual(engagement.tickets[0].customer_id, orders.customers[0].customer_id)
        self.assertEqual(result["order_id"], str(orders.orders[0].order_id))

    def test_generates_refunds_when_mix_requires_it(self) -> None:
        orders = FakeOrders()
        billing = FakeBilling()
        engagement = FakeEngagement()
        scenario = DemoScenario(
            orders=orders,
            billing=billing,
            engagement=engagement,
            mix=ScenarioMix(failure_rate=0.0, refund_rate=1.0, sla_breach_rate=0.0),
            random_seed=1,
        )

        result = scenario.run_once()

        self.assertEqual(len(billing.refunds), 1)
        self.assertEqual(billing.payments[0].payment_status, "captured")
        self.assertEqual(billing.refunds[0].payment_id, billing.payments[0].payment_id)
        self.assertEqual(result["refund_id"], billing.refunds[0].refund_id)

    def test_generates_sla_breach_when_mix_requires_it(self) -> None:
        orders = FakeOrders()
        billing = FakeBilling()
        engagement = FakeEngagement()
        scenario = DemoScenario(
            orders=orders,
            billing=billing,
            engagement=engagement,
            mix=ScenarioMix(failure_rate=0.0, refund_rate=0.0, sla_breach_rate=1.0),
            random_seed=2,
        )

        scenario.run_once()

        ticket = engagement.tickets[0]
        self.assertIn(ticket.priority, {"high", "critical"})
        self.assertIn(ticket.status, {"open", "waiting_customer"})
        self.assertLess(ticket.sla_due_at, ticket.opened_at)

    def test_generates_postgres_inventory_fallback_records(self) -> None:
        orders = FakeOrders()
        billing = FakeBilling()
        engagement = FakeEngagement()
        inventory = FakeInventory()
        scenario = DemoScenario(
            orders=orders,
            billing=billing,
            engagement=engagement,
            inventory=inventory,
            random_seed=3,
        )

        result = scenario.run_once()

        self.assertEqual(len(inventory.products), 1)
        self.assertEqual(len(inventory.movements), 1)
        self.assertEqual(orders.items[0].product_id, inventory.products[0].product_id)
        self.assertEqual(inventory.movements[0].product_id, inventory.products[0].product_id)
        self.assertEqual(result["product_id"], inventory.products[0].product_id)
        self.assertEqual(result["stock_movement_id"], inventory.movements[0].movement_id)

    def test_rejects_invalid_scenario_mix_rates(self) -> None:
        with self.assertRaises(ValueError):
            ScenarioMix(failure_rate=1.1)


if __name__ == "__main__":
    unittest.main()
