CREATE KEYSPACE IF NOT EXISTS omnicare_dashboard
WITH REPLICATION = {
  'class': 'SimpleStrategy',
  'replication_factor': 1
};

CREATE TABLE IF NOT EXISTS omnicare_dashboard.dim_customer_by_id (
  customer_id text PRIMARY KEY,
  hospital_name text,
  segment text,
  city text,
  country text,
  source_topic text,
  source_position text,
  event_ts timestamp,
  deleted boolean
);

CREATE TABLE IF NOT EXISTS omnicare_dashboard.dim_product_by_id (
  product_id text PRIMARY KEY,
  sku text,
  product_name text,
  product_category text,
  supplier_id text,
  source_topic text,
  source_position text,
  event_ts timestamp,
  deleted boolean
);

CREATE TABLE IF NOT EXISTS omnicare_dashboard.fact_order_line_by_day (
  order_day date,
  fact_id text,
  order_id text,
  order_item_id text,
  customer_id text,
  product_id text,
  channel text,
  quantity int,
  unit_price_cents bigint,
  gross_amount_cents bigint,
  order_status text,
  source_topic text,
  source_position text,
  event_ts timestamp,
  op text,
  PRIMARY KEY ((order_day), fact_id)
);

CREATE TABLE IF NOT EXISTS omnicare_dashboard.fact_payment_by_day (
  payment_day date,
  fact_id text,
  payment_id text,
  invoice_id text,
  order_id text,
  customer_id text,
  payment_status text,
  payment_method text,
  amount_cents bigint,
  source_topic text,
  source_position text,
  event_ts timestamp,
  op text,
  PRIMARY KEY ((payment_day), fact_id)
);

CREATE TABLE IF NOT EXISTS omnicare_dashboard.fact_inventory_movement_by_product (
  product_id text,
  movement_ts timestamp,
  fact_id text,
  movement_id text,
  warehouse_id text,
  movement_type text,
  quantity int,
  source_topic text,
  source_position text,
  event_ts timestamp,
  op text,
  PRIMARY KEY ((product_id), movement_ts, fact_id)
) WITH CLUSTERING ORDER BY (movement_ts DESC);

CREATE TABLE IF NOT EXISTS omnicare_dashboard.fact_support_case_by_customer (
  customer_id text,
  opened_day date,
  fact_id text,
  ticket_id text,
  priority text,
  status text,
  sla_due_at timestamp,
  closed_at timestamp,
  source_topic text,
  source_position text,
  event_ts timestamp,
  op text,
  PRIMARY KEY ((customer_id), opened_day, fact_id)
) WITH CLUSTERING ORDER BY (opened_day DESC);

