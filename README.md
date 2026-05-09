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
- Production backlog and runbooks.

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

## First Build Slice

This initial V2 slice includes:

- Architecture docs.
- Ticket backlog.
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
CDC_SOURCE_TOPICS=cdc.local.omnicare.postgres.public.customers,cdc.local.omnicare.postgres.public.order_items,cdc.local.omnicare.mysql.billing.payments,cdc.local.omnicare.mongo.engagement.support_tickets \
  omnicare-cdc-transformer --max-messages 100 --idle-timeout-seconds 10
```

To replay Kafka into an empty Cassandra keyspace, use a new `KAFKA_GROUP_ID`. The target writes are idempotent through deterministic fact IDs and Cassandra upserts.

## Register Local Connectors

Local connector JSON files contain environment placeholders. Render and register them with:

```bash
ENV_FILE=.env scripts/register-connectors.sh
```

In production, prefer Kafka Connect config providers or a platform secrets integration instead of rendering secrets into JSON files.

Validate connector templates and required environment variables without starting containers:

```bash
python tools/validate_config.py
```

## Generate Demo Data

Install and run the generator:

```bash
cd generator
python -m pip install -e .
omnicare-demo-generator --iterations 10
```

The generator writes to PostgreSQL, MySQL, and MongoDB using driver parameter binding / document APIs. Oracle generator support is intentionally deferred because the local Oracle profile is optional.

Host-side MongoDB writes use `directConnection=true` because the local replica set advertises the internal Compose hostname to Debezium. The Debezium Mongo connector still uses the internal replica-set address from inside the Compose network.

## Local Migrations

Fresh containers apply `postgres/init.sql` and `mysql/init.sql`. If an older local container already exists, apply the migration SQL under `migrations/local` or recreate that source container. The migrations capture schema compatibility fixes found during E2E testing:

- `postgres/001_order_item_context.sql`: denormalized order context needed by order-line facts.
- `mysql/001_payment_context.sql`: payment context and widened prefixed IDs.
- `mysql/002_debezium_privileges.sql`: local Debezium snapshot/binlog privileges.

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
http://localhost:19090          # Prometheus
http://localhost:13000          # Grafana, admin/admin
```

The exporter reads Kafka Connect status and the dashboard API snapshot, then exposes connector health, task health, dashboard API health, snapshot freshness, and dashboard summary values as Prometheus metrics. Grafana auto-provisions the `OmniCare CDC Operations` dashboard from `observability/grafana/dashboards`.

This is the starter operational layer. Full production hardening still needs Kafka consumer lag and Debezium/JMX internals for source lag and connector throughput.

## Production Rule

This demo assumes at-least-once CDC delivery. Correctness is enforced through idempotent target writes and deterministic fact ids.
