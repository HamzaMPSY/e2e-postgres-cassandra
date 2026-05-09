SET @add_order_id = (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE payments ADD COLUMN order_id VARCHAR(36) NULL AFTER invoice_id',
    'SELECT 1'
  )
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'payments'
    AND column_name = 'order_id'
);
PREPARE stmt FROM @add_order_id;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @add_customer_id = (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE payments ADD COLUMN customer_id VARCHAR(36) NULL AFTER order_id',
    'SELECT 1'
  )
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'payments'
    AND column_name = 'customer_id'
);
PREPARE stmt FROM @add_customer_id;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

ALTER TABLE invoices MODIFY invoice_id VARCHAR(64);
ALTER TABLE payments MODIFY payment_id VARCHAR(64);
ALTER TABLE payments MODIFY invoice_id VARCHAR(64);
ALTER TABLE refunds MODIFY refund_id VARCHAR(64);
ALTER TABLE refunds MODIFY payment_id VARCHAR(64);

UPDATE payments p
JOIN invoices i ON i.invoice_id = p.invoice_id
SET
  p.order_id = COALESCE(p.order_id, i.order_id),
  p.customer_id = COALESCE(p.customer_id, i.customer_id)
WHERE p.order_id IS NULL
   OR p.customer_id IS NULL;
