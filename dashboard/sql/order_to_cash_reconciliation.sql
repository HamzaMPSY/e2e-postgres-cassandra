WITH orders AS (
  SELECT
    order_id,
    customer_id,
    min(order_day) AS first_order_day,
    sum(gross_amount_cents) AS ordered_amount_cents
  FROM cassandra.omnicare_dashboard.fact_order_line_by_day
  GROUP BY order_id, customer_id
),
payments AS (
  SELECT
    order_id,
    customer_id,
    min(payment_day) AS first_payment_day,
    sum(CASE WHEN payment_status = 'captured' THEN amount_cents ELSE 0 END) AS captured_amount_cents,
    sum(CASE WHEN payment_status = 'failed' THEN amount_cents ELSE 0 END) AS failed_amount_cents
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
  (o.ordered_amount_cents - COALESCE(p.captured_amount_cents, 0)) / 100.0 AS open_amount
FROM orders o
LEFT JOIN payments p
  ON p.order_id = o.order_id
ORDER BY open_amount DESC, o.first_order_day DESC;
