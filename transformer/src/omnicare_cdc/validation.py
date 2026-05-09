from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import StarRow


PAYMENT_STATUSES = {"captured", "failed", "pending"}
PAYMENT_METHODS = {"card", "wire", "insurance"}
ORDER_STATUSES = {"confirmed", "allocated", "shipped", "backordered"}
ORDER_CHANNELS = {"portal", "edi", "sales_rep"}
REFUND_REASONS = {"duplicate_charge", "returned_goods", "contract_adjustment"}
INVENTORY_MOVEMENT_TYPES = {"receipt", "shipment", "adjustment_in", "adjustment_out"}
SUPPORT_PRIORITIES = {"low", "medium", "high", "critical"}
SUPPORT_STATUSES = {"open", "waiting_customer", "resolved"}
COMMON_VALUES = ("source_topic", "source_position", "event_ts")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    table: str
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "validation_error_code": self.code,
            "table": self.table,
            "field": self.field,
            "message": self.message,
        }


class RowValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        preview = "; ".join(
            f"{issue.code} {issue.table}.{issue.field}: {issue.message}"
            for issue in issues[:3]
        )
        suffix = f"; +{len(issues) - 3} more" if len(issues) > 3 else ""
        super().__init__(f"{preview}{suffix}")

    def to_metadata(self) -> dict[str, Any]:
        first = self.issues[0]
        return {
            "validation_error_code": first.code,
            "table": first.table,
            "field": first.field,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class TableRule:
    key_required: tuple[str, ...]
    value_required: tuple[str, ...] = COMMON_VALUES
    value_required_when_active: tuple[str, ...] = ()
    positive: tuple[str, ...] = ()
    non_negative: tuple[str, ...] = ()
    enums: dict[str, set[str]] = field(default_factory=dict)


RULES = {
    "dim_customer_by_id": TableRule(
        key_required=("customer_id",),
        value_required_when_active=("hospital_name", "segment", "city", "country"),
    ),
    "dim_product_by_id": TableRule(
        key_required=("product_id",),
        value_required_when_active=(
            "sku",
            "product_name",
            "product_category",
            "supplier_id",
        ),
    ),
    "fact_order_line_by_day": TableRule(
        key_required=("order_day", "fact_id"),
        value_required=(
            *COMMON_VALUES,
            "order_id",
            "order_item_id",
            "customer_id",
            "product_id",
            "channel",
            "quantity",
            "unit_price_cents",
            "gross_amount_cents",
            "order_status",
        ),
        positive=("quantity",),
        non_negative=("unit_price_cents", "gross_amount_cents"),
        enums={"order_status": ORDER_STATUSES, "channel": ORDER_CHANNELS},
    ),
    "fact_payment_by_day": TableRule(
        key_required=("payment_day", "fact_id"),
        value_required=(
            *COMMON_VALUES,
            "payment_id",
            "invoice_id",
            "order_id",
            "customer_id",
            "payment_status",
            "payment_method",
            "amount_cents",
        ),
        non_negative=("amount_cents",),
        enums={"payment_status": PAYMENT_STATUSES, "payment_method": PAYMENT_METHODS},
    ),
    "fact_refund_by_day": TableRule(
        key_required=("refund_day", "fact_id"),
        value_required=(
            *COMMON_VALUES,
            "refund_id",
            "payment_id",
            "refund_reason",
            "amount_cents",
        ),
        non_negative=("amount_cents",),
        enums={"refund_reason": REFUND_REASONS},
    ),
    "fact_inventory_movement_by_product": TableRule(
        key_required=("product_id", "movement_ts", "fact_id"),
        value_required=(
            *COMMON_VALUES,
            "movement_id",
            "warehouse_id",
            "movement_type",
            "quantity",
        ),
        positive=("quantity",),
        enums={"movement_type": INVENTORY_MOVEMENT_TYPES},
    ),
    "fact_support_case_by_customer": TableRule(
        key_required=("customer_id", "opened_day", "fact_id"),
        value_required=(*COMMON_VALUES, "ticket_id", "priority", "status"),
        enums={"priority": SUPPORT_PRIORITIES, "status": SUPPORT_STATUSES},
    ),
}


def validate_star_rows(rows: list[StarRow]) -> list[StarRow]:
    issues = [issue for row in rows for issue in _validate_row(row)]
    if issues:
        raise RowValidationError(issues)
    return rows


def _validate_row(row: StarRow) -> list[ValidationIssue]:
    rule = RULES.get(row.table)
    if rule is None:
        return [_issue(row, "table", "unknown_target_table", "unregistered table")]

    value_required = rule.value_required
    if not row.values.get("deleted"):
        value_required = (*value_required, *rule.value_required_when_active)

    issues = _required(row, row.key, rule.key_required)
    issues.extend(_required(row, row.values, value_required))
    for field_name in rule.positive:
        issues.extend(_number(row, field_name, minimum=1, code="non_positive_number"))
    for field_name in rule.non_negative:
        issues.extend(_number(row, field_name, minimum=0, code="negative_number"))
    for field_name, allowed in rule.enums.items():
        issues.extend(_enum(row, field_name, allowed))
    return issues


def _required(
    row: StarRow,
    data: dict[str, Any],
    fields: tuple[str, ...],
) -> list[ValidationIssue]:
    return [
        _issue(row, field_name, "required_field_missing", "missing, null, or blank")
        for field_name in fields
        if _is_blank(data.get(field_name))
    ]


def _number(
    row: StarRow,
    field_name: str,
    *,
    minimum: int,
    code: str,
) -> list[ValidationIssue]:
    parsed = _int_or_none(row.values.get(field_name))
    if parsed is None:
        return [_issue(row, field_name, "invalid_integer", "must be an integer")]
    if parsed < minimum:
        message = "must be greater than zero" if minimum == 1 else "must not be negative"
        return [_issue(row, field_name, code, message)]
    return []


def _enum(row: StarRow, field_name: str, allowed: set[str]) -> list[ValidationIssue]:
    value = row.values.get(field_name)
    if _is_blank(value) or str(value) in allowed:
        return []
    return [
        _issue(
            row,
            field_name,
            "unknown_enum_value",
            f"must be one of: {', '.join(sorted(allowed))}",
        )
    ]


def _issue(row: StarRow, field_name: str, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code, row.table, field_name, message)


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "none", "null"}
    return False
