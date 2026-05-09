# OmniCare CDC

Production-grade multi-source CDC demo:

```text
PostgreSQL + MySQL + MongoDB + optional Oracle
  -> Debezium Kafka Connect
  -> Kafka raw CDC topics
  -> Python transformer
  -> Cassandra dashboard star tables
  -> Trino
  -> Browser dashboard + Prometheus/Grafana observability
```

## Why this exists

The original project demonstrated Postgres to Cassandra CDC. This version turns that into an enterprise-style demo:

- Multiple applications.
- Multiple database engines.
- CDC connector templates.
- Cassandra serving schema.
- Trino SQL access.
- Tested transformation code.
- Browser dashboard and observability starter stack.
- Production runbooks and deployment templates.

## Quick Start

```bash
cp .env.example .env
podman compose --env-file .env -f docker-compose.yaml up -d
```

The local Compose file is intentionally memory-tuned for a laptop Podman machine. It caps JVM-heavy services such as Kafka, Kafka Connect, Schema Registry, Trino, and Cassandra. This is a development profile, not a production sizing model.

The MySQL container is pinned to `mysql:8.0` because Debezium 2.7 uses MySQL binlog metadata commands that are not compatible with the `mysql:8.4` image in this local stack. Production deployments should pin and certify every source database and connector version as a pair.

Oracle is optional:

```bash
podman compose --env-file .env -f docker-compose.yaml --profile oracle up -d
```

For a guided local end-to-end demo, run:

```bash
scripts/demo-e2e.sh --max-events 25 --rate-per-second 5
```

The harness starts the stack, registers connectors, generates source data, runs a bounded transformer smoke pass, verifies Cassandra and dashboard data, and writes `artifacts/demo-report.json`. Details are in `docs/v2/DEMO_HARNESS.md`.

CI runs the harness in a container-free dry-run smoke profile on every push and pull request. A manually gated live Podman profile is documented in `docs/v2/CI_E2E_SMOKE.md` for prepared self-hosted runners.

## First Build Slice

This initial V2 slice includes:

- Architecture docs.
- Ignored local ticket board for execution tracking.
- Local Compose skeleton.
- Source DB init scripts.
- Cassandra schema.
- Debezium connector templates.
- Trino Cassandra catalog.
- Python transformation package with unit tests.

## Test Transformer

```bash
cd transformer
PYTHONPATH=src python -m unittest
```

## Run Transformer

Install the transformer in a virtual environment:

```bash
cd transformer
python -m pip install -e .
omnicare-cdc-transformer
```

The service disables Kafka auto-commit. It writes transformed rows to Cassandra first, then commits the source Kafka offset. If a record fails parsing or writing, it publishes a DLQ record and then commits the source offset to avoid a poison-message loop.

The transformer exposes Prometheus metrics by default on port `8090`. When it runs through Compose, the host URL is:

```text
http://localhost:18092/metrics
```

Metrics include processed message counters, DLQ counters by source topic, rows written, and Cassandra write latency.

For local smoke tests, run a finite batch against only the active local topics:

```bash
CDC_SOURCE_TOPICS=cdc.local.omnicare.postgres.public.customers,cdc.local.omnicare.postgres.public.order_items,cdc.local.omnicare.postgres.public.products,cdc.local.omnicare.postgres.public.stock_movements,cdc.local.omnicare.mysql.billing.payments,cdc.local.omnicare.mysql.billing.refunds,cdc.local.omnicare.mongo.engagement.support_tickets \
  omnicare-cdc-transformer --max-messages 100 --idle-timeout-seconds 10
```

To replay Kafka into an empty Cassandra keyspace, use a new `KAFKA_GROUP_ID`. Dimension writes are upserts; fact rows include the source position, so resnapshot recovery should follow the runbook before broad dashboard use.

## Register Local Connectors

Local connector JSON files contain environment placeholders. Render and register them with:

```bash
ENV_FILE=.env scripts/register-connectors.sh
```

In production, prefer Kafka Connect config providers or a platform secrets integration instead of rendering secrets into JSON files.

Production connector templates live under `connectors/production/`. They use config provider references for secrets, source/Kafka TLS settings, and redacted connector logging defaults. The contract is documented in `docs/v2/CONNECTOR_TEMPLATES.md`.

Validate connector templates and required environment variables without starting containers:

```bash
python tools/validate_config.py
python tools/security_check.py
```

## Generate Demo Data

Install and run the generator:

```bash
cd generator
python -m pip install -e .
omnicare-demo-generator --max-events 500 --rate-per-second 5
```

The generator writes orders and the local inventory fallback to PostgreSQL, invoices/payments/refunds to MySQL, and support tickets to MongoDB using driver parameter binding / document APIs. Oracle generator support is intentionally deferred because the local Oracle profile is optional; when Oracle is not active, `GENERATOR_INVENTORY_SOURCE=postgres-fallback` publishes product and stock-movement CDC through PostgreSQL so the inventory dashboard path still has data.

Useful long-running controls:

```bash
omnicare-demo-generator \
  --iterations 0 \
  --duration-seconds 300 \
  --rate-per-second 10 \
  --failure-rate 0.20 \
  --refund-rate 0.10 \
  --sla-breach-rate 0.15
```

`--max-events` stops after a fixed count, `--duration-seconds` stops after elapsed wall time, and `--iterations 0` removes the count limit for duration-based or continuous runs. `--inventory-source oracle` disables the PostgreSQL inventory fallback when a real Oracle inventory feed is active.

Host-side MongoDB writes use `directConnection=true` because the local replica set advertises the internal Compose hostname to Debezium. The Debezium Mongo connector still uses the internal replica-set address from inside the Compose network.

## Local Migrations

Fresh containers apply the init files under `postgres`, `mysql`, `mongo`, and `oracle`. If an older local container already exists, apply the migration files under `migrations/local` or recreate that source container. The migrations capture schema compatibility fixes found during E2E testing:

- `postgres/001_order_item_context.sql`: denormalized order context needed by order-line facts.
- `postgres/002_debezium_signal.sql`: Debezium source signal table for incremental snapshots.
- `postgres/003_inventory_fallback.sql`: optional local inventory tables when the Oracle profile is not active.
- `mysql/001_payment_context.sql`: payment context and widened prefixed IDs.
- `mysql/002_debezium_privileges.sql`: local Debezium snapshot/binlog privileges.
- `mysql/003_debezium_signal.sql`: Debezium source signal table for incremental snapshots.
- `mongo/001_debezium_signal.js`: Debezium source signal collection for incremental snapshots.

## Recovery Runbooks

Replay, resnapshot, and recovery operations are documented in `docs/v2/RUNBOOKS.md`.

Production security controls are documented in `docs/v2/SECURITY_HARDENING.md` and enforced by `tools/security_check.py`.

AWS, GCP, and datacenter deployment skeletons are documented in `docs/v2/DEPLOYMENT.md` and validated by `tools/validate_deployments.py`.

Common commands:

```bash
scripts/cdc-replay.sh --topic cdc.local.omnicare.postgres.public.customers --max-messages 1000
scripts/request-resnapshot.sh --connector postgres-orders-local --data-collection public.customers
scripts/connect-connector.sh status postgres-orders-local
scripts/connect-connector.sh offsets postgres-orders-local
```

## Latest Verified Smoke Test

Validated locally on 2026-05-08:

- PostgreSQL, MySQL, and MongoDB Debezium connectors were `RUNNING`.
- Generator created coherent cross-database order, payment, and support flows.
- Transformer replayed `47` CDC messages into a fresh Cassandra keyspace.
- Cassandra contained `14` order-line facts, `7` payment facts, and `12` support-case facts.
- Trino queried Cassandra successfully; revenue-by-day returned `2026-05-08`, `14` order lines, and `6079.8` gross revenue.

Validated after root promotion on 2026-05-09:

- Dashboard API returned live revenue, payment, support, and order-to-cash data.
- Config validation passed with an explicit Oracle template warning.

## Dashboard UI

The lightweight dashboard is served from the Compose stack:

```text
http://localhost:18090
```

It queries Trino over HTTP, then renders revenue, payment health, support risk, and order-to-cash cards from Cassandra serving tables.

## Observability

The local stack includes a first production-style observability slice:

```text
http://localhost:18091/metrics  # project metrics exporter
http://localhost:19308/metrics  # Kafka consumer lag exporter
http://localhost:18778/jolokia  # Kafka Connect Jolokia/JMX endpoint
http://localhost:19090          # Prometheus
http://localhost:13000          # Grafana, admin/admin
```

The exporter reads Kafka Connect status, Debezium JMX through Jolokia, and the dashboard API snapshot, then exposes connector health, task health, source lag, Debezium event throughput, dashboard API health, snapshot freshness, and dashboard summary values as Prometheus metrics. Kafka exporter adds consumer-group lag metrics. Grafana auto-provisions the `OmniCare CDC Operations` dashboard from `observability/grafana/dashboards`.

This is still a local observability profile, not a production monitoring platform. In production, wire the same metrics into managed Prometheus/Grafana or your platform standard, add retention, alert routing, SLOs, and service ownership.

## Production Rule

This demo assumes at-least-once CDC delivery. Correctness is enforced through idempotent target writes and deterministic fact ids.
