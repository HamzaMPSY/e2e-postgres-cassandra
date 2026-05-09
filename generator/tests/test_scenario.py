from __future__ import annotations

import unittest

from omnicare_generator.scenario import DemoScenario


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

    def insert_invoice(self, invoice) -> None:
        self.invoices.append(invoice)

    def insert_payment(self, payment) -> None:
        self.payments.append(payment)


class FakeEngagement:
    def __init__(self) -> None:
        self.tickets = []

    def insert_ticket(self, ticket) -> None:
        self.tickets.append(ticket)


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
        self.assertEqual(len(engagement.tickets), 1)
        self.assertEqual(orders.items[0].order_id, orders.orders[0].order_id)
        self.assertEqual(billing.invoices[0].order_id, orders.orders[0].order_id)
        self.assertEqual(billing.payments[0].order_id, orders.orders[0].order_id)
        self.assertEqual(billing.payments[0].customer_id, orders.customers[0].customer_id)
        self.assertEqual(engagement.tickets[0].customer_id, orders.customers[0].customer_id)
        self.assertEqual(result["order_id"], str(orders.orders[0].order_id))


if __name__ == "__main__":
    unittest.main()
