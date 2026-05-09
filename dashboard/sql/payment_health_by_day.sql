SELECT
  payment_day,
  payment_status,
  count(*) AS payment_count,
  sum(amount_cents) / 100.0 AS amount
FROM cassandra.omnicare_dashboard.fact_payment_by_day
GROUP BY payment_day, payment_status
ORDER BY payment_day DESC, payment_status;

