CREATE TABLE IF NOT EXISTS debezium_signal (
  id VARCHAR(42) PRIMARY KEY,
  type VARCHAR(32) NOT NULL,
  data VARCHAR(2048)
);

ALTER TABLE debezium_signal REPLICA IDENTITY FULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_publication_tables
    WHERE pubname = 'dbz_omnicare_orders'
      AND schemaname = 'public'
      AND tablename = 'debezium_signal'
  ) THEN
    ALTER PUBLICATION dbz_omnicare_orders ADD TABLE debezium_signal;
  END IF;
END $$;
