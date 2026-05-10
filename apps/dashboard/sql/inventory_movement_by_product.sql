SELECT
  m.product_id,
  p.sku,
  p.product_name,
  p.product_category,
  sum(CASE WHEN m.movement_type IN ('receipt', 'adjustment_in') THEN m.quantity ELSE 0 END) AS inbound_units,
  sum(CASE WHEN m.movement_type IN ('shipment', 'adjustment_out') THEN m.quantity ELSE 0 END) AS outbound_units,
  sum(
    CASE
      WHEN m.movement_type IN ('receipt', 'adjustment_in') THEN m.quantity
      WHEN m.movement_type IN ('shipment', 'adjustment_out') THEN -m.quantity
      ELSE 0
    END
  ) AS net_units
FROM cassandra.omnicare_dashboard.fact_inventory_movement_by_product m
LEFT JOIN cassandra.omnicare_dashboard.dim_product_by_id p
  ON p.product_id = m.product_id
GROUP BY m.product_id, p.sku, p.product_name, p.product_category
ORDER BY net_units ASC, m.product_id;
