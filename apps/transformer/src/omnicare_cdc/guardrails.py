from __future__ import annotations

from dataclasses import dataclass, field

from .models import StarRow
from .validation import BusinessRules, RowValidationError, ValidationIssue


@dataclass
class BusinessGuardrails:
    rules: BusinessRules
    _customers: set[str] = field(default_factory=set)
    _order_totals: dict[str, int] = field(default_factory=dict)
    _order_lines: dict[str, tuple[str, int]] = field(default_factory=dict)

    def validate(self, rows: list[StarRow]) -> list[StarRow]:
        issues = [issue for row in rows for issue in self._validate_payment(row)]
        if issues:
            raise RowValidationError(issues)
        return rows

    def observe(self, rows: list[StarRow]) -> None:
        for row in rows:
            if row.table == "dim_customer_by_id" and not row.values.get("deleted"):
                self._customers.add(str(row.key["customer_id"]))
            elif row.table == "fact_order_line_by_day":
                self._observe_order_line(row)

    def _observe_order_line(self, row: StarRow) -> None:
        order_id = str(row.values["order_id"])
        order_item_id = str(row.values["order_item_id"])
        amount = int(row.values["gross_amount_cents"])
        customer_id = row.values.get("customer_id")
        if customer_id is not None:
            self._customers.add(str(customer_id))

        previous = self._order_lines.get(order_item_id)
        if previous is not None:
            previous_order_id, previous_amount = previous
            self._order_totals[previous_order_id] = (
                self._order_totals.get(previous_order_id, 0) - previous_amount
            )

        self._order_lines[order_item_id] = (order_id, amount)
        self._order_totals[order_id] = self._order_totals.get(order_id, 0) + amount

    def _validate_payment(self, row: StarRow) -> list[ValidationIssue]:
        if row.table != "fact_payment_by_day":
            return []

        order_id = str(row.values.get("order_id"))
        customer_id = str(row.values.get("customer_id"))
        issues: list[ValidationIssue] = []

        if self.rules.reference_validation_mode == "strict":
            if order_id not in self._order_totals:
                issues.append(
                    _issue(row, "order_id", "unknown_order_reference", "order is unknown")
                )
            if customer_id not in self._customers:
                issues.append(
                    _issue(
                        row,
                        "customer_id",
                        "unknown_customer_reference",
                        "customer is unknown",
                    )
                )

        order_total = self._order_totals.get(order_id)
        if order_total is None or row.values.get("payment_status") != "captured":
            return issues

        amount = int(row.values["amount_cents"])
        allowed = order_total + self.rules.payment_overpay_tolerance_cents
        if amount > allowed:
            issues.append(
                _issue(
                    row,
                    "amount_cents",
                    "payment_amount_exceeds_order_total",
                    "captured payment exceeds known order total plus tolerance",
                )
            )
        return issues


def _issue(row: StarRow, field: str, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code, row.table, field, message)
