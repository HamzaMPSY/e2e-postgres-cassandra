SELECT
  customer_id,
  opened_day,
  priority,
  status,
  count(*) AS ticket_count
FROM cassandra.omnicare_dashboard.fact_support_case_by_customer
GROUP BY customer_id, opened_day, priority, status
ORDER BY opened_day DESC, ticket_count DESC;

