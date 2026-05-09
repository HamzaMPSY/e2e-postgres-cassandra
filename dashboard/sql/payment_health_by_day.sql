SELECT
  activity_day AS payment_day,
  payment_status,
  count(*) AS payment_count,
  sum(amount_cents) / 100.0 AS amount
FROM (
  SELECT
    payment_day AS activity_day,
    payment_status,
    amount_cents
  FROM cassandra.omnicare_dashboard.fact_payment_by_day
  UNION ALL
  SELECT
    refund_day AS activity_day,
    'refunded' AS payment_status,
    -amount_cents AS amount_cents
  FROM cassandra.omnicare_dashboard.fact_refund_by_day
)
GROUP BY activity_day, payment_status
ORDER BY activity_day DESC, payment_status;
