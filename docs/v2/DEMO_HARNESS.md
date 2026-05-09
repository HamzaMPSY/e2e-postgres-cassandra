# End-to-End Demo Harness

`scripts/demo-e2e.sh` is the operator-friendly local demo command for CDCV2-017. It is designed for interview and stakeholder demos where the goal is to show the whole CDC path without manually running every step.

## What It Runs

```text
Podman Compose stack
  -> Debezium connector registration
  -> bounded source data generator
  -> bounded transformer smoke consumer
  -> Cassandra row-count verification
  -> dashboard API non-empty verification
  -> JSON demo report
```

Default command:

```bash
scripts/demo-e2e.sh
```

The script expects a local env file:

```bash
cp .env.example .env
```

For a small demo:

```bash
scripts/demo-e2e.sh \
  --max-events 25 \
  --rate-per-second 5 \
  --transformer-max-messages 300 \
  --report-file artifacts/demo-report.json
```

## CI-Friendly Dry Run

The dry run prints the planned commands and does not require containers:

```bash
scripts/demo-e2e.sh --dry-run --env-file .env.example
```

CI covers the dry-run path and bash syntax. Live container execution stays manual because the stack is intentionally heavier than a normal pull-request job.

## Verification Gates

The harness fails if:

- Kafka Connect does not answer.
- The dashboard health endpoint does not answer.
- Local connectors do not reach `RUNNING` state.
- Cassandra serving tables stay empty.
- The dashboard API does not return non-empty revenue data.

Verified Cassandra tables:

- `fact_order_line_by_day`
- `fact_payment_by_day`
- `fact_support_case_by_customer`
- `fact_inventory_movement_by_product`

## Report

The JSON report includes:

- Cassandra row counts.
- Dashboard summary metrics.
- Dashboard, Grafana, and Prometheus URLs.
- A `status=passed` marker.

Default report path:

```text
artifacts/demo-report.json
```
