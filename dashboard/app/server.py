from __future__ import annotations

import json
import mimetypes
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from quality import DEFAULT_MAX_EVENT_AGE_SECONDS, quality_report


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"


class TrinoClient:
    def __init__(self, base_url: str, user: str = "omnicare_dashboard"):
        self._base_url = base_url.rstrip("/")
        self._user = user

    def query(self, sql: str) -> list[dict[str, Any]]:
        response = self._request(
            f"{self._base_url}/v1/statement",
            method="POST",
            body=sql.encode("utf-8"),
        )
        rows: list[dict[str, Any]] = []

        while True:
            if "error" in response:
                message = response["error"].get("message", "unknown Trino error")
                raise RuntimeError(message)

            rows.extend(_rows_from_response(response))
            next_uri = response.get("nextUri")
            if not next_uri:
                return rows

            response = self._request(next_uri, method="GET")

    def _request(
        self,
        url: str,
        *,
        method: str,
        body: bytes | None = None,
    ) -> dict[str, Any]:
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "X-Trino-User": self._user,
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))


def _rows_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    columns = response.get("columns") or []
    data = response.get("data") or []
    names = [column["name"] for column in columns]
    return [dict(zip(names, row, strict=False)) for row in data]


class DashboardData:
    def __init__(self, trino: TrinoClient):
        self._trino = trino

    def snapshot(self) -> dict[str, Any]:
        generated_at = int(time.time())
        revenue = self._safe_query("revenue", REVENUE_BY_DAY)
        payments = self._safe_query("payments", PAYMENT_HEALTH)
        support = self._safe_query("support", SUPPORT_RISK)
        order_cash = self._safe_query("orderCash", ORDER_TO_CASH)
        quality_findings = self._safe_query("qualityFindings", QUALITY_FINDINGS)
        max_event_age_seconds = _freshness_window_seconds()

        return {
            "generatedAt": generated_at,
            "summary": _summary(revenue, payments, support, order_cash),
            "dataQuality": quality_report(
                generated_at=generated_at,
                revenue=revenue,
                payments=payments,
                support=support,
                order_cash=order_cash,
                quality_findings=quality_findings,
                operational_metrics=_transformer_quality_metrics(),
                warning_checks=_warning_checks(),
                dlq_max_records=_quality_threshold("DASHBOARD_DLQ_MAX_RECORDS", 0),
                quarantine_max_records=_quality_threshold(
                    "DASHBOARD_QUARANTINE_MAX_RECORDS",
                    0,
                ),
                max_event_age_seconds=max_event_age_seconds,
            ),
            "revenueByDay": revenue,
            "paymentHealth": payments,
            "supportRisk": support,
            "orderToCash": order_cash[:20],
            "qualityFindings": quality_findings,
        }

    def _safe_query(self, name: str, sql: str) -> list[dict[str, Any]]:
        try:
            return self._trino.query(sql)
        except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
            return [{"error": f"{name}: {exc}"}]


def _summary(
    revenue: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    support: list[dict[str, Any]],
    order_cash: list[dict[str, Any]],
) -> dict[str, Any]:
    valid_revenue = [row for row in revenue if "error" not in row]
    valid_payments = [row for row in payments if "error" not in row]
    valid_support = [row for row in support if "error" not in row]
    valid_order_cash = [row for row in order_cash if "error" not in row]

    gross_revenue = sum(float(row.get("gross_revenue") or 0) for row in valid_revenue)
    order_lines = sum(int(row.get("order_lines") or 0) for row in valid_revenue)
    payment_amount = sum(float(row.get("amount") or 0) for row in valid_payments)
    payment_count = sum(int(row.get("payment_count") or 0) for row in valid_payments)
    support_cases = sum(int(row.get("ticket_count") or 0) for row in valid_support)
    open_amount = sum(float(row.get("open_amount") or 0) for row in valid_order_cash)

    return {
        "grossRevenue": round(gross_revenue, 2),
        "orderLines": order_lines,
        "paymentAmount": round(payment_amount, 2),
        "paymentCount": payment_count,
        "supportCases": support_cases,
        "openAmount": round(open_amount, 2),
    }


def _freshness_window_seconds() -> int:
    try:
        value = int(
            os.environ.get(
                "DASHBOARD_FRESHNESS_MAX_AGE_SECONDS",
                str(DEFAULT_MAX_EVENT_AGE_SECONDS),
            )
        )
    except ValueError:
        return DEFAULT_MAX_EVENT_AGE_SECONDS
    return value if value > 0 else DEFAULT_MAX_EVENT_AGE_SECONDS


def _quality_threshold(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value >= 0 else default


def _warning_checks() -> set[str]:
    raw = os.environ.get("DASHBOARD_QUALITY_WARNING_CHECKS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _transformer_quality_metrics() -> dict[str, Any]:
    url = os.environ.get("TRANSFORMER_METRICS_URL", "").strip()
    if not url:
        return {}
    try:
        with urlopen(url, timeout=3) as response:
            text = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {"telemetryAvailable": False, "metricsError": str(exc)}

    return {
        "telemetryAvailable": True,
        "dlqRecordCount": _prometheus_metric_sum(
            text,
            "omnicare_transformer_dlq_records_total",
        ),
        "quarantineRecordCount": _prometheus_metric_sum(
            text,
            "omnicare_transformer_validation_rejects_total",
        ),
    }


def _prometheus_metric_sum(text: str, metric_name: str) -> int:
    total = 0.0
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, raw_value = line.partition(" ")
        if name == metric_name or name.startswith(f"{metric_name}{{"):
            try:
                total += float(raw_value.strip())
            except ValueError:
                continue
    return int(total)


class Handler(BaseHTTPRequestHandler):
    data = DashboardData(
        TrinoClient(os.environ.get("TRINO_URL", "http://trino:8080"))
    )

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._json({"status": "ok"})
            return
        if path == "/api/dashboard":
            self._json(self.data.snapshot())
            return
        if path == "/":
            path = "/index.html"

        static_path = (STATIC_ROOT / path.lstrip("/")).resolve()
        if not str(static_path).startswith(str(STATIC_ROOT)) or not static_path.exists():
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(static_path.name)[0] or "application/octet-stream"
        content = static_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("DASHBOARD_ACCESS_LOG", "false").lower() == "true":
            super().log_message(format, *args)

    def _json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


REVENUE_BY_DAY = """
SELECT
  order_day,
  count(*) AS order_lines,
  sum(quantity) AS units_ordered,
  sum(gross_amount_cents) / 100.0 AS gross_revenue,
  max(event_ts) AS last_event_ts
FROM cassandra.omnicare_dashboard.fact_order_line_by_day
GROUP BY order_day
ORDER BY order_day DESC
"""

PAYMENT_HEALTH = """
SELECT
  activity_day AS payment_day,
  payment_status,
  count(*) AS payment_count,
  sum(amount_cents) / 100.0 AS amount,
  max(event_ts) AS last_event_ts
FROM (
  SELECT
    payment_day AS activity_day,
    payment_status,
    amount_cents,
    event_ts
  FROM cassandra.omnicare_dashboard.fact_payment_by_day
  UNION ALL
  SELECT
    refund_day AS activity_day,
    'refunded' AS payment_status,
    -amount_cents AS amount_cents,
    event_ts
  FROM cassandra.omnicare_dashboard.fact_refund_by_day
)
GROUP BY activity_day, payment_status
ORDER BY activity_day DESC, payment_status
"""

SUPPORT_RISK = """
SELECT
  opened_day,
  priority,
  status,
  count(*) AS ticket_count,
  max(event_ts) AS last_event_ts
FROM cassandra.omnicare_dashboard.fact_support_case_by_customer
GROUP BY opened_day, priority, status
ORDER BY opened_day DESC, ticket_count DESC
"""

ORDER_TO_CASH = """
WITH orders AS (
  SELECT
    order_id,
    customer_id,
    min(order_day) AS first_order_day,
    sum(gross_amount_cents) AS ordered_amount_cents,
    max(event_ts) AS last_order_event_ts
  FROM cassandra.omnicare_dashboard.fact_order_line_by_day
  GROUP BY order_id, customer_id
),
payments AS (
  SELECT
    order_id,
    customer_id,
    min(payment_day) AS first_payment_day,
    sum(CASE WHEN payment_status = 'captured' THEN amount_cents ELSE 0 END) AS captured_amount_cents,
    sum(CASE WHEN payment_status = 'failed' THEN amount_cents ELSE 0 END) AS failed_amount_cents,
    max(event_ts) AS last_payment_event_ts
  FROM cassandra.omnicare_dashboard.fact_payment_by_day
  GROUP BY order_id, customer_id
)
SELECT
  o.order_id,
  COALESCE(o.customer_id, p.customer_id) AS customer_id,
  o.first_order_day,
  p.first_payment_day,
  o.ordered_amount_cents / 100.0 AS ordered_amount,
  p.captured_amount_cents / 100.0 AS captured_amount,
  p.failed_amount_cents / 100.0 AS failed_amount,
  (o.ordered_amount_cents - COALESCE(p.captured_amount_cents, 0)) / 100.0 AS open_amount,
  GREATEST(
    COALESCE(o.last_order_event_ts, TIMESTAMP '1970-01-01 00:00:00'),
    COALESCE(p.last_payment_event_ts, TIMESTAMP '1970-01-01 00:00:00')
  ) AS last_event_ts
FROM orders o
LEFT JOIN payments p
  ON p.order_id = o.order_id
ORDER BY open_amount DESC, o.first_order_day DESC
"""

QUALITY_FINDINGS = """
WITH payment_findings AS (
  SELECT
    sum(CASE WHEN amount_cents < 0 THEN 1 ELSE 0 END) AS negative_payment_facts,
    sum(
      CASE
        WHEN payment_status IS NULL
          OR payment_status NOT IN ('captured', 'failed', 'pending')
          OR payment_method IS NULL
          OR payment_method NOT IN ('card', 'wire', 'insurance')
        THEN 1
        ELSE 0
      END
    ) AS unknown_payment_enums,
    sum(
      CASE
        WHEN payment_id IS NULL
          OR invoice_id IS NULL
          OR order_id IS NULL
          OR customer_id IS NULL
        THEN 1
        ELSE 0
      END
    ) AS null_payment_dimensions
  FROM cassandra.omnicare_dashboard.fact_payment_by_day
),
refund_findings AS (
  SELECT
    sum(CASE WHEN amount_cents < 0 THEN 1 ELSE 0 END) AS negative_refund_facts,
    sum(
      CASE
        WHEN refund_reason IS NULL
          OR refund_reason NOT IN (
            'duplicate_charge',
            'returned_goods',
            'contract_adjustment'
          )
        THEN 1
        ELSE 0
      END
    ) AS unknown_refund_enums
  FROM cassandra.omnicare_dashboard.fact_refund_by_day
),
order_findings AS (
  SELECT
    sum(
      CASE
        WHEN order_id IS NULL
          OR order_item_id IS NULL
          OR customer_id IS NULL
          OR product_id IS NULL
        THEN 1
        ELSE 0
      END
    ) AS null_order_dimensions,
    sum(
      CASE
        WHEN order_status IS NULL
          OR order_status NOT IN ('confirmed', 'allocated', 'shipped', 'backordered')
          OR channel IS NULL
          OR channel NOT IN ('portal', 'edi', 'sales_rep')
        THEN 1
        ELSE 0
      END
    ) AS unknown_order_enums
  FROM cassandra.omnicare_dashboard.fact_order_line_by_day
),
support_findings AS (
  SELECT
    sum(
      CASE
        WHEN customer_id IS NULL
          OR ticket_id IS NULL
          OR priority IS NULL
          OR status IS NULL
        THEN 1
        ELSE 0
      END
    ) AS null_support_dimensions,
    sum(
      CASE
        WHEN priority IS NULL
          OR priority NOT IN ('low', 'medium', 'high', 'critical')
          OR status IS NULL
          OR status NOT IN ('open', 'waiting_customer', 'resolved')
        THEN 1
        ELSE 0
      END
    ) AS unknown_support_enums
  FROM cassandra.omnicare_dashboard.fact_support_case_by_customer
),
inventory_findings AS (
  SELECT
    sum(
      CASE
        WHEN product_id IS NULL
          OR movement_id IS NULL
          OR warehouse_id IS NULL
        THEN 1
        ELSE 0
      END
    ) AS null_inventory_dimensions,
    sum(
      CASE
        WHEN movement_type IS NULL
          OR movement_type NOT IN (
            'receipt',
            'shipment',
            'adjustment_in',
            'adjustment_out'
          )
        THEN 1
        ELSE 0
      END
    ) AS unknown_inventory_enums
  FROM cassandra.omnicare_dashboard.fact_inventory_movement_by_product
),
customer_findings AS (
  SELECT
    sum(
      CASE
        WHEN customer_id IS NULL
          OR hospital_name IS NULL
          OR segment IS NULL
          OR city IS NULL
          OR country IS NULL
        THEN 1
        ELSE 0
      END
    ) AS null_customer_dimensions
  FROM cassandra.omnicare_dashboard.dim_customer_by_id
),
product_findings AS (
  SELECT
    sum(
      CASE
        WHEN product_id IS NULL
          OR sku IS NULL
          OR product_name IS NULL
          OR product_category IS NULL
          OR supplier_id IS NULL
        THEN 1
        ELSE 0
      END
    ) AS null_product_dimensions
  FROM cassandra.omnicare_dashboard.dim_product_by_id
)
SELECT
  COALESCE(payment_findings.negative_payment_facts, 0) AS negative_payment_facts,
  COALESCE(refund_findings.negative_refund_facts, 0) AS negative_refund_facts,
  COALESCE(customer_findings.null_customer_dimensions, 0) AS null_customer_dimensions,
  COALESCE(product_findings.null_product_dimensions, 0) AS null_product_dimensions,
  COALESCE(order_findings.null_order_dimensions, 0) AS null_order_dimensions,
  COALESCE(payment_findings.null_payment_dimensions, 0) AS null_payment_dimensions,
  COALESCE(support_findings.null_support_dimensions, 0) AS null_support_dimensions,
  COALESCE(inventory_findings.null_inventory_dimensions, 0) AS null_inventory_dimensions,
  COALESCE(order_findings.unknown_order_enums, 0) AS unknown_order_enums,
  COALESCE(payment_findings.unknown_payment_enums, 0) AS unknown_payment_enums,
  COALESCE(refund_findings.unknown_refund_enums, 0) AS unknown_refund_enums,
  COALESCE(support_findings.unknown_support_enums, 0) AS unknown_support_enums,
  COALESCE(inventory_findings.unknown_inventory_enums, 0) AS unknown_inventory_enums
FROM payment_findings
CROSS JOIN refund_findings
CROSS JOIN order_findings
CROSS JOIN support_findings
CROSS JOIN inventory_findings
CROSS JOIN customer_findings
CROSS JOIN product_findings
"""


def main() -> None:
    port = int(os.environ.get("DASHBOARD_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"OmniCare dashboard listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
