ALTER TABLE order_items
  ADD COLUMN IF NOT EXISTS customer_id UUID,
  ADD COLUMN IF NOT EXISTS channel TEXT,
  ADD COLUMN IF NOT EXISTS order_status TEXT,
  ADD COLUMN IF NOT EXISTS ordered_at TIMESTAMPTZ;

UPDATE order_items oi
SET
  customer_id = o.customer_id,
  channel = o.channel,
  order_status = o.order_status,
  ordered_at = o.ordered_at
FROM orders o
WHERE oi.order_id = o.order_id
  AND (
    oi.customer_id IS NULL
    OR oi.channel IS NULL
    OR oi.order_status IS NULL
    OR oi.ordered_at IS NULL
  );
