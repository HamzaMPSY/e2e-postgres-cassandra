from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


DEFAULT_MAX_EVENT_AGE_SECONDS = 86_400


def quality_report(
    *,
    generated_at: int,
    revenue: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    support: list[dict[str, Any]],
    order_cash: list[dict[str, Any]],
    quality_findings: list[dict[str, Any]] | None = None,
    operational_metrics: dict[str, Any] | None = None,
    warning_checks: set[str] | None = None,
    dlq_max_records: int = 0,
    quarantine_max_records: int = 0,
    max_event_age_seconds: int = DEFAULT_MAX_EVENT_AGE_SECONDS,
) -> dict[str, Any]:
    checks = [
        _query_success_check(revenue, payments, support, order_cash, quality_findings or []),
        _row_count_check(revenue, payments, support),
        _amount_reconciliation_check(revenue, payments, order_cash),
        _payment_amount_anomaly_check(quality_findings or []),
        _required_dimensions_check(quality_findings or []),
        _enum_domain_check(quality_findings or []),
        _dlq_quarantine_threshold_check(
            operational_metrics or {},
            dlq_max_records=dlq_max_records,
            quarantine_max_records=quarantine_max_records,
        ),
        _freshness_check(
            generated_at,
            [*revenue, *payments, *support, *order_cash],
            max_event_age_seconds,
        ),
    ]
    checks = _apply_warning_overrides(checks, warning_checks or set())
    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    return {
        "overallStatus": overall,
        "maxEventAgeSeconds": max_event_age_seconds,
        "checks": checks,
    }


def _query_success_check(*datasets: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [
        str(row.get("error"))
        for dataset in datasets
        for row in dataset
        if row.get("error")
    ]
    return _check(
        "dashboard_queries_ok",
        "fail" if errors else "pass",
        "dashboard SQL queries must complete without partial error rows",
        {"errors": errors},
    )


def _row_count_check(
    revenue: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    support: list[dict[str, Any]],
) -> dict[str, Any]:
    negative_rows = []
    for name, rows, fields in (
        ("revenueByDay", revenue, ("order_lines", "units_ordered")),
        ("paymentHealth", payments, ("payment_count",)),
        ("supportRisk", support, ("ticket_count",)),
    ):
        for index, row in enumerate(_valid_rows(rows)):
            for field in fields:
                if _number(row.get(field)) < 0:
                    negative_rows.append(f"{name}[{index}].{field}")
    return _check(
        "non_negative_row_counts",
        "fail" if negative_rows else "pass",
        "aggregated row-count metrics must never be negative",
        {"negativeRows": negative_rows},
    )


def _amount_reconciliation_check(
    revenue: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    order_cash: list[dict[str, Any]],
) -> dict[str, Any]:
    gross_revenue = sum(_number(row.get("gross_revenue")) for row in _valid_rows(revenue))
    captured = sum(
        _number(row.get("amount"))
        for row in _valid_rows(payments)
        if str(row.get("payment_status")) == "captured"
    )
    refunds = abs(
        sum(
            _number(row.get("amount"))
            for row in _valid_rows(payments)
            if str(row.get("payment_status")) == "refunded"
        )
    )
    net_captured = captured - refunds
    negative_open_orders = [
        str(row.get("order_id", f"row-{index}"))
        for index, row in enumerate(_valid_rows(order_cash))
        if _number(row.get("open_amount")) < -0.01
    ]

    failures = []
    if gross_revenue < -0.01:
        failures.append("gross revenue is negative")
    if net_captured < -0.01:
        failures.append("net captured payments are negative")
    if net_captured - gross_revenue > 0.01:
        failures.append("net captured payments exceed gross revenue")
    if negative_open_orders:
        failures.append("orders have negative open amounts")

    return _check(
        "order_payment_reconciliation",
        "fail" if failures else "pass",
        "captured payments minus refunds must not exceed ordered revenue",
        {
            "grossRevenue": round(gross_revenue, 2),
            "capturedPayments": round(captured, 2),
            "refunds": round(refunds, 2),
            "netCapturedPayments": round(net_captured, 2),
            "negativeOpenOrders": negative_open_orders,
            "failures": failures,
        },
    )


def _payment_amount_anomaly_check(
    quality_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    findings = _quality_counts(quality_findings)
    failures = {
        "negativePaymentFacts": int(findings.get("negative_payment_facts", 0)),
        "negativeRefundFacts": int(findings.get("negative_refund_facts", 0)),
    }
    total = sum(failures.values())
    return _check(
        "serving_payment_amounts_valid",
        "fail" if total else "pass",
        "raw payment and refund facts must not contain negative source amounts",
        {"totalInvalidFacts": total, **failures},
    )


def _required_dimensions_check(
    quality_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    findings = _quality_counts(quality_findings)
    failures = {
        "nullCustomerDimensions": int(findings.get("null_customer_dimensions", 0)),
        "nullProductDimensions": int(findings.get("null_product_dimensions", 0)),
        "nullOrderDimensions": int(findings.get("null_order_dimensions", 0)),
        "nullPaymentDimensions": int(findings.get("null_payment_dimensions", 0)),
        "nullSupportDimensions": int(findings.get("null_support_dimensions", 0)),
        "nullInventoryDimensions": int(findings.get("null_inventory_dimensions", 0)),
    }
    total = sum(failures.values())
    return _check(
        "serving_required_dimensions_present",
        "fail" if total else "pass",
        "serving facts must keep required dashboard dimensions populated",
        {"totalInvalidFacts": total, **failures},
    )


def _enum_domain_check(
    quality_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    findings = _quality_counts(quality_findings)
    failures = {
        "unknownOrderEnums": int(findings.get("unknown_order_enums", 0)),
        "unknownPaymentEnums": int(findings.get("unknown_payment_enums", 0)),
        "unknownRefundEnums": int(findings.get("unknown_refund_enums", 0)),
        "unknownSupportEnums": int(findings.get("unknown_support_enums", 0)),
        "unknownInventoryEnums": int(findings.get("unknown_inventory_enums", 0)),
    }
    total = sum(failures.values())
    return _check(
        "serving_enum_values_known",
        "fail" if total else "pass",
        "serving facts must use known enum/domain values",
        {"totalInvalidFacts": total, **failures},
    )


def _dlq_quarantine_threshold_check(
    operational_metrics: dict[str, Any],
    *,
    dlq_max_records: int,
    quarantine_max_records: int,
) -> dict[str, Any]:
    dlq_count = int(_number(operational_metrics.get("dlqRecordCount")))
    quarantine_count = int(_number(operational_metrics.get("quarantineRecordCount")))
    failures = []
    if dlq_count > dlq_max_records:
        failures.append("DLQ record count exceeds threshold")
    if quarantine_count > quarantine_max_records:
        failures.append("quarantine reject count exceeds threshold")

    return _check(
        "dlq_quarantine_thresholds",
        "fail" if failures else "pass",
        "DLQ and transformer quarantine counts must stay within configured thresholds",
        {
            "dlqRecordCount": dlq_count,
            "dlqMaxRecords": dlq_max_records,
            "quarantineRecordCount": quarantine_count,
            "quarantineMaxRecords": quarantine_max_records,
            "telemetryAvailable": bool(operational_metrics.get("telemetryAvailable")),
            "metricsError": operational_metrics.get("metricsError"),
            "failures": failures,
        },
    )


def _freshness_check(
    generated_at: int,
    rows: list[dict[str, Any]],
    max_event_age_seconds: int,
) -> dict[str, Any]:
    timestamps = [
        parsed
        for row in _valid_rows(rows)
        for parsed in [_parse_timestamp(row.get("last_event_ts") or row.get("event_ts"))]
        if parsed is not None
    ]
    if not timestamps:
        return _check(
            "pipeline_event_freshness",
            "warn",
            "materialized rows should expose last_event_ts for freshness gates",
            {"maxAgeSeconds": None},
        )

    newest = max(timestamps)
    snapshot_time = datetime.fromtimestamp(generated_at, tz=timezone.utc)
    age_seconds = max(0, int((snapshot_time - newest).total_seconds()))
    status = "fail" if age_seconds > max_event_age_seconds else "pass"
    return _check(
        "pipeline_event_freshness",
        status,
        "newest materialized event must be within the configured freshness window",
        {
            "newestEventTs": newest.isoformat(),
            "ageSeconds": age_seconds,
        },
    )


def _check(name: str, status: str, description: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "description": description,
        "details": details,
    }


def _apply_warning_overrides(
    checks: list[dict[str, Any]],
    warning_checks: set[str],
) -> list[dict[str, Any]]:
    if not warning_checks:
        return checks

    updated = []
    for check in checks:
        if check["status"] == "fail" and check["name"] in warning_checks:
            details = dict(check.get("details") or {})
            details["configuredAsWarning"] = True
            check = {**check, "status": "warn", "details": details}
        updated.append(check)
    return updated


def _quality_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    valid_rows = _valid_rows(rows)
    if not valid_rows:
        return {}
    counts: dict[str, int] = {}
    for key, value in valid_rows[0].items():
        counts[key] = int(_number(value))
    return counts


def _valid_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if "error" not in row]


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).replace(" UTC", "+00:00").replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
