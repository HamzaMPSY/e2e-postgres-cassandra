SELECT
  order_day,
  count(*) AS order_lines,
  sum(quantity) AS units_ordered,
  sum(gross_amount_cents) / 100.0 AS gross_revenue
FROM cassandra.omnicare_dashboard.fact_order_line_by_day
GROUP BY order_day
ORDER BY order_day DESC;

