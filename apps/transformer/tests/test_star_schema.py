from __future__ import annotations

import unittest

from omnicare_cdc.star_schema import to_star_rows


class StarSchemaMappingTest(unittest.TestCase):
    def test_maps_order_item_to_fact_row(self) -> None:
        event = {
            "payload": {
                "op": "c",
                "ts_ms": 1710000000000,
                "source": {
                    "db": "orders",
                    "schema": "public",
                    "table": "order_items",
                    "lsn": 42,
                },
                "after": {
                    "order_item_id": "line-1",
                    "order_id": "order-1",
                    "customer_id": "customer-1",
                    "product_id": "product-1",
                    "quantity": 3,
                    "unit_price_cents": 2500,
                    "ordered_at": "2026-05-07T10:00:00+00:00",
                    "channel": "portal",
                    "order_status": "confirmed",
                },
            }
        }

        rows = to_star_rows("cdc.local.omnicare.postgres.public.order_items", event)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].table, "fact_order_line_by_day")
        self.assertEqual(rows[0].values["gross_amount_cents"], 7500)
        self.assertEqual(rows[0].values["source_position"], "lsn:42")

    def test_fact_id_is_stable_for_replay(self) -> None:
        event = {
            "payload": {
                "op": "u",
                "ts_ms": 1710000000000,
                "source": {"table": "payments", "file": "mysql-bin.000001", "pos": 120},
                "after": {
                    "payment_id": "pay-1",
                    "invoice_id": "inv-1",
                    "order_id": "order-1",
                    "customer_id": "customer-1",
                    "payment_status": "captured",
                    "payment_method": "card",
                    "amount_cents": 10000,
                    "paid_at": "2026-05-07T11:00:00+00:00",
                },
            }
        }

        first = to_star_rows("cdc.local.omnicare.mysql.billing.payments", event)
        second = to_star_rows("cdc.local.omnicare.mysql.billing.payments", event)

        self.assertEqual(first[0].key["fact_id"], second[0].key["fact_id"])

    def test_maps_refund_to_fact_row(self) -> None:
        event = {
            "payload": {
                "op": "c",
                "ts_ms": 1710000000000,
                "source": {"table": "refunds", "file": "mysql-bin.000001", "pos": 180},
                "after": {
                    "refund_id": "ref-1",
                    "payment_id": "pay-1",
                    "refund_reason": "returned_goods",
                    "amount_cents": 2500,
                    "refunded_at": "2026-05-07T12:00:00+00:00",
                },
            }
        }

        rows = to_star_rows("cdc.local.omnicare.mysql.billing.refunds", event)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].table, "fact_refund_by_day")
        self.assertEqual(rows[0].values["payment_id"], "pay-1")
        self.assertEqual(rows[0].values["amount_cents"], 2500)

    def test_maps_postgres_inventory_fallback_to_existing_inventory_tables(self) -> None:
        product_event = {
            "payload": {
                "op": "c",
                "ts_ms": 1710000000000,
                "source": {"table": "products", "lsn": 300},
                "after": {
                    "product_id": "P-MASK-200",
                    "sku": "MASK-200",
                    "product_name": "Respirator Mask Box",
                    "product_category": "ppe",
                    "supplier_id": "SUP-MED-03",
                },
            }
        }
        movement_event = {
            "payload": {
                "op": "c",
                "ts_ms": 1710000000000,
                "source": {"table": "stock_movements", "lsn": 301},
                "after": {
                    "movement_id": "MOV-1",
                    "product_id": "P-MASK-200",
                    "warehouse_id": "WH-CASA-01",
                    "movement_type": "shipment",
                    "quantity": 4,
                    "movement_ts": "2026-05-07T12:30:00+00:00",
                },
            }
        }

        product_rows = to_star_rows("cdc.local.omnicare.postgres.public.products", product_event)
        movement_rows = to_star_rows(
            "cdc.local.omnicare.postgres.public.stock_movements",
            movement_event,
        )

        self.assertEqual(product_rows[0].table, "dim_product_by_id")
        self.assertEqual(product_rows[0].key["product_id"], "P-MASK-200")
        self.assertEqual(movement_rows[0].table, "fact_inventory_movement_by_product")
        self.assertEqual(movement_rows[0].key["product_id"], "P-MASK-200")

    def test_maps_delete_to_deleted_dimension(self) -> None:
        event = {
            "payload": {
                "op": "d",
                "ts_ms": 1710000000000,
                "source": {"table": "customers", "lsn": 99},
                "before": {
                    "customer_id": "customer-1",
                    "hospital_name": "Central Hospital",
                    "segment": "enterprise",
                    "city": "Casablanca",
                    "country": "MA",
                },
            }
        }

        rows = to_star_rows("cdc.local.omnicare.postgres.public.customers", event)

        self.assertEqual(rows[0].table, "dim_customer_by_id")
        self.assertTrue(rows[0].values["deleted"])

    def test_unknown_table_is_ignored(self) -> None:
        event = {
            "payload": {
                "op": "c",
                "source": {"table": "unknown_table"},
                "after": {"id": "1"},
            }
        }

        self.assertEqual(to_star_rows("cdc.local.omnicare.postgres.public.unknown", event), [])

    def test_maps_mongo_json_string_document_to_support_fact(self) -> None:
        event = {
            "payload": {
                "op": "c",
                "ts_ms": 1710000000000,
                "source": {
                    "db": "engagement",
                    "collection": "support_tickets",
                    "ord": 7,
                },
                "after": """
                {
                  "ticket_id": "ticket-1",
                  "customer_id": "customer-1",
                  "priority": "critical",
                  "status": "open",
                  "opened_at": {"$date": 1778235462000},
                  "sla_due_at": {"$date": 1778249862000},
                  "closed_at": null
                }
                """,
            }
        }

        rows = to_star_rows("cdc.local.omnicare.mongo.engagement.support_tickets", event)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].table, "fact_support_case_by_customer")
        self.assertEqual(rows[0].key["customer_id"], "customer-1")
        self.assertEqual(rows[0].values["priority"], "critical")


if __name__ == "__main__":
    unittest.main()
