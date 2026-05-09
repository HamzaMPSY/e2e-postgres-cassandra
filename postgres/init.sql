CREATE TABLE IF NOT EXISTS customers (
  customer_id UUID PRIMARY KEY,
  hospital_name TEXT NOT NULL,
  segment TEXT NOT NULL,
  city TEXT NOT NULL,
  country TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
  order_id UUID PRIMARY KEY,
  customer_id UUID NOT NULL REFERENCES customers(customer_id),
  order_status TEXT NOT NULL,
  channel TEXT NOT NULL,
  ordered_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS order_items (
  order_item_id UUID PRIMARY KEY,
  order_id UUID NOT NULL REFERENCES orders(order_id),
  customer_id UUID NOT NULL REFERENCES customers(customer_id),
  product_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  order_status TEXT NOT NULL,
  ordered_at TIMESTAMPTZ NOT NULL,
  quantity INT NOT NULL CHECK (quantity > 0),
  unit_price_cents BIGINT NOT NULL CHECK (unit_price_cents >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS debezium_signal (
  id VARCHAR(42) PRIMARY KEY,
  type VARCHAR(32) NOT NULL,
  data VARCHAR(2048)
);

ALTER TABLE customers REPLICA IDENTITY FULL;
ALTER TABLE orders REPLICA IDENTITY FULL;
ALTER TABLE order_items REPLICA IDENTITY FULL;
ALTER TABLE debezium_signal REPLICA IDENTITY FULL;

CREATE PUBLICATION dbz_omnicare_orders FOR TABLE customers, orders, order_items, debezium_signal;
