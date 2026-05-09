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
                max_event_age_seconds=max_event_age_seconds,
            ),
            "revenueByDay": revenue,
            "paymentHealth": payments,
            "supportRisk": support,
            "orderToCash": order_cash[:20],
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


def main() -> None:
    port = int(os.environ.get("DASHBOARD_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"OmniCare dashboard listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
