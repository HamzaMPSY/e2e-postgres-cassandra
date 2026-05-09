CREATE TABLE IF NOT EXISTS products (
  product_id TEXT PRIMARY KEY,
  sku TEXT NOT NULL,
  product_name TEXT NOT NULL,
  product_category TEXT NOT NULL,
  supplier_id TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock_movements (
  movement_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL REFERENCES products(product_id),
  warehouse_id TEXT NOT NULL,
  movement_type TEXT NOT NULL,
  quantity INT NOT NULL CHECK (quantity > 0),
  movement_ts TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE products REPLICA IDENTITY FULL;
ALTER TABLE stock_movements REPLICA IDENTITY FULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_publication_tables
    WHERE pubname = 'dbz_omnicare_orders'
      AND schemaname = 'public'
      AND tablename = 'products'
  ) THEN
    ALTER PUBLICATION dbz_omnicare_orders ADD TABLE products;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_publication_tables
    WHERE pubname = 'dbz_omnicare_orders'
      AND schemaname = 'public'
      AND tablename = 'stock_movements'
  ) THEN
    ALTER PUBLICATION dbz_omnicare_orders ADD TABLE stock_movements;
  END IF;
END $$;
