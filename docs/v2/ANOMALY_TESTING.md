# Anomaly Injection Harness

`scripts/anomaly-e2e.sh` turns the manual bad-data test into a repeatable local command. It is intended for hardening work after the normal demo path is already healthy.

## What It Proves

```text
source constraint rejects
  -> accepted semantic anomalies
  -> bounded transformer consumer
  -> DLQ/quarantine delta checks
  -> Cassandra serving-table delta checks
  -> dashboard quality gate
  -> JSON anomaly report
```

The harness exercises three failure layers:

- Source constraints: PostgreSQL rejects negative order quantity and null product references; MySQL rejects null payment amount.
- Transformer row validation: malformed or incomplete rows are not written to Cassandra.
- Business guardrails: negative captured payments and impossible payment amounts are sent to the transformer DLQ.

## Command

Run this after the local stack and connectors are already up:

```bash
scripts/anomaly-e2e.sh \
  --skip-start \
  --skip-register-connectors \
  --cleanup \
  --transformer-max-messages 500 \
  --report-file artifacts/anomaly-report.json
```

Run a command preview without containers:

```bash
scripts/anomaly-e2e.sh \
  --dry-run \
  --env-file .env.example \
  --transformer-max-messages 10
```

## Scenarios

| Source | Scenario | Expected result |
|---|---|---|
| PostgreSQL orders | Negative `order_items.quantity` | Source insert fails |
| PostgreSQL orders | Null `order_items.product_id` | Source insert fails |
| MySQL billing | Null `payments.amount_cents` | Source insert fails |
| MySQL billing | Captured payment with huge amount | Transformer DLQ |
| MySQL billing | Captured payment with negative amount | Transformer DLQ |
| MySQL billing | Pending payment with null `paid_at` | Accepted with fallback timestamp |
| MongoDB engagement | Support ticket with null customer/status/priority | Transformer DLQ |
| MongoDB engagement | Support ticket missing `ticket_id` | Transformer DLQ |
| MongoDB engagement | Support ticket with malformed `opened_at` | Transformer DLQ |

## Pass Criteria

The script fails if:

- A source constraint reject unexpectedly succeeds.
- The expected pending payment anomaly is not materialized exactly once.
- The negative or impossible captured payment anomalies reach `fact_payment_by_day`.
- The malformed support anomalies reach `fact_support_case_by_customer`.
- Fewer than four anomaly records are observed in `dlq.local.omnicare.transformer`.
- `tools/quality_gate.py` rejects the dashboard snapshot.

The generated report includes:

- Source reject outcomes.
- Cassandra row deltas.
- Exact anomaly record counts.
- DLQ delta.
- Dashboard summary.
- Dashboard data quality status.
- Dashboard, Grafana, and Prometheus URLs.

Default report path:

```text
artifacts/anomaly-report.json
```

## Operational Notes

Use `--cleanup` when rerunning on a dirty local stack. The cleanup removes prior anomaly rows from MySQL, MongoDB, and Cassandra before inserting a fresh batch. PostgreSQL source-reject scenarios do not persist rows because the database rejects them.

The harness runs the transformer with `podman compose run --rm --no-deps` and an isolated `KAFKA_GROUP_ID`. That keeps the command aligned with the image built by `podman compose` without requiring the long-running transformer container to be healthy, and it makes the anomaly consumer replayable without changing the default transformer group.
