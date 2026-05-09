from __future__ import annotations

import unittest
from pathlib import Path


class SourceConstraintsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[2]

    def test_mysql_billing_has_non_negative_financial_checks(self) -> None:
        content = (self.root / "mysql" / "init.sql").read_text(encoding="utf-8")

        self.assertIn("CHECK (amount_cents >= 0)", content)
        self.assertIn("CHECK (payment_status IN ('captured', 'failed', 'pending'))", content)
        self.assertIn("CHECK (payment_method IN ('card', 'wire', 'insurance'))", content)
        self.assertIn(
            "CHECK (refund_reason IN "
            "('duplicate_charge', 'returned_goods', 'contract_adjustment'))",
            content,
        )

    def test_mongo_support_tickets_have_strict_json_schema(self) -> None:
        content = (self.root / "mongo" / "init.js").read_text(encoding="utf-8")

        self.assertIn("supportTicketValidator", content)
        self.assertIn(
            'required: ["ticket_id", "customer_id", "priority", "status", "opened_at"]',
            content,
        )
        self.assertIn('ticket_id: { bsonType: "string", minLength: 1 }', content)
        self.assertIn('customer_id: { bsonType: "string", minLength: 1 }', content)
        self.assertIn('priority: { enum: ["low", "medium", "high", "critical"] }', content)
        self.assertIn('status: { enum: ["open", "waiting_customer", "resolved"] }', content)
        self.assertIn('opened_at: { bsonType: "date" }', content)
        self.assertIn('validationLevel: "strict"', content)
        self.assertIn('validationAction: "error"', content)

    def test_compose_runs_committed_mongo_initializer(self) -> None:
        content = (self.root / "docker-compose.yaml").read_text(encoding="utf-8")

        self.assertIn("./mongo/init.js:/opt/omnicare/mongo-init.js:ro", content)
        self.assertIn("/opt/omnicare/mongo-init.js", content)


if __name__ == "__main__":
    unittest.main()
