# Production CDC Build Backlog

This backlog is ordered to create a production-grade demo incrementally. P0 tickets build the platform spine. P1 tickets make it end-to-end. P2 tickets make it interview-polished and cloud-ready.

Last updated: 2026-05-09

## Current Runtime Snapshot

Validated in local Podman:

- Kafka container is running and healthy.
- Kafka Connect REST API is reachable.
- PostgreSQL Debezium connector is `RUNNING`.
- MySQL Debezium connector is `RUNNING` after adding `database.server.id`, schema history topic config, MySQL CDC privileges, and pinning the local image to `mysql:8.0`.
- MongoDB Debezium connector is `RUNNING` after moving replica-set setup into a setup job.
- Cassandra schema setup job exited `0` and the `omnicare_dashboard` keyspace/tables were verified with `cqlsh`.
- Trino starts and queries Cassandra after setting `cassandra.load-policy.dc-aware.local-dc=datacenter1`.
- Transformer unit tests pass: `10 tests OK`.
- Generator unit tests pass: `1 test OK`.
- Generator produced coherent records across PostgreSQL, MySQL, and MongoDB.
- Transformer replay smoke test processed `47` CDC messages into a fresh Cassandra keyspace.
- Cassandra verification after replay:
  - `fact_order_line_by_day`: `14` rows.
  - `fact_payment_by_day`: `7` rows.
  - `fact_support_case_by_customer`: `12` rows.
- Trino verification query returned `14` order lines for `2026-05-08` with `6079.8` gross revenue.
- Lightweight dashboard UI service was added and is reachable at `http://localhost:18090`.

Known current issues:

- Dashboard service is built and healthy, but needs one final replay validation after the root promotion.
- Dashboard API returned live revenue, payment, support, and order-to-cash data after root promotion.
- Config validation CLI passes for active local connectors and warns that Oracle is template-only.
- Observability starter stack now includes a custom metrics exporter, transformer metrics, Prometheus scrape config, starter alert rules, and provisioned Grafana dashboard.
- Superset dashboard import is not built; the custom UI is now the default demo dashboard.
- Oracle remains a connector/schema template only; it is intentionally not part of the default laptop E2E run.
- Inventory facts need an active Oracle or replacement inventory generator to become visible.

## P0 - Foundation

### CDCV2-001: Define V2 domain and data contracts

Priority: P0

Status: Done

Scope:

- Define source applications and ownership.
- Define source tables/collections.
- Define raw CDC topic names.
- Define star-schema target tables.
- Define idempotency keys for each fact table.

Acceptance criteria:

- [x] `docs/v2/USE_CASE.md` exists.
- [x] `docs/v2/ARCHITECTURE.md` exists.
- [x] Every source entity maps to at least one target dimension or fact.
- [x] Every fact table has a deterministic dedupe key.

### CDCV2-002: Create production-style local Compose stack

Priority: P0

Status: Mostly done

Scope:

- Add Kafka, Schema Registry, Kafka Connect, PostgreSQL, MySQL, MongoDB, Cassandra, Trino.
- Add Oracle as optional profile because it is heavy and license-sensitive.
- Add healthchecks where practical.
- Use `.env.example` instead of hard-coded credentials.

Acceptance criteria:

- [x] `docker-compose.yaml` exists.
- [x] `.env.example` documents all required variables.
- [x] Core services can be started without Oracle.
- [x] Oracle is isolated behind a Compose profile.
- [x] Add resource tuning or lighter profiles so Cassandra does not exit with code `137` on the local Podman machine.
- [ ] Replace weak local health status with real service healthchecks where the image supports it.

### CDCV2-003: Add source database schemas and seed plan

Priority: P0

Status: Done for active local sources

Scope:

- PostgreSQL DDL for orders and customers.
- MySQL DDL for invoices, payments, refunds.
- MongoDB collection/index initialization.
- Oracle DDL template for ERP products and stock movements.

Acceptance criteria:

- [x] DDL/init files exist under `postgres`, `mysql`, `mongo`, `oracle`.
- [x] Tables have primary keys.
- [x] Source records include `created_at` and `updated_at` where useful, but CDC does not depend on polling those columns.
- [x] Add realistic seed/generator data for cross-database dashboard flows.
- [x] Add migration files for schema fixes discovered during E2E validation.

### CDCV2-004: Add connector config templates

Priority: P0

Status: Done for active local sources

Scope:

- Debezium PostgreSQL connector.
- Debezium MySQL connector.
- Debezium MongoDB connector.
- Debezium Oracle connector template.
- DLQ and heartbeat defaults.

Acceptance criteria:

- [x] Connector configs exist under `connectors`.
- [x] Configs use environment placeholders for secrets.
- [x] Topic naming follows `cdc.local.<domain>.<database>.<schema>.<table>`.
- [x] Local registration script is idempotent: creates or updates connector config.
- [x] PostgreSQL connector task verified `RUNNING`.
- [x] MySQL connector task verified `RUNNING`.
- [x] MongoDB connector task verified `RUNNING`.
- [ ] Oracle connector remains a template only and is not validated locally.

### CDCV2-005: Add Cassandra serving schema

Priority: P0

Status: Done

Scope:

- Create keyspace.
- Create dimension tables.
- Create fact tables.
- Include source metadata columns for replay and dedupe.

Acceptance criteria:

- [x] `cassandra/schema.cql` exists.
- [x] Each fact table stores source topic, source position, event timestamp, and operation metadata.
- [x] Current-state dimensions and dashboard fact tables are separated.
- [x] Schema setup job added to Compose.
- [x] `omnicare_dashboard` keyspace and tables verified with `cqlsh`.
- [x] Cassandra runtime revalidated after local memory tuning.

## P1 - End-to-End Pipeline

### CDCV2-006: Build transformation service

Priority: P1

Status: Done

Scope:

- Consume Debezium envelopes.
- Normalize operation type, source table, timestamps, and source position.
- Map raw events to star-schema rows.
- Add idempotency key generation.

Acceptance criteria:

- [x] Python package exists under `transformer`.
- [x] Unit tests cover inserts, deletes, duplicate replay, source-position handling, Cassandra write shape, and DLQ commit behavior.
- [x] No production logic lives in notebooks.
- [x] `PYTHONPATH=src python -m unittest` passes with 10 tests.

### CDCV2-007: Add Kafka consumer and Cassandra writer

Priority: P1

Status: Done for active local sources

Scope:

- Add Kafka consumer loop.
- Add Cassandra session management.
- Write dimension/fact rows idempotently.
- Commit offsets only after successful writes.

Acceptance criteria:

- [x] Consumer can subscribe to source topics.
- [x] Failed records go to DLQ.
- [x] Replaying the same event does not create duplicate facts through deterministic fact ids and Cassandra upserts.
- [x] Kafka offset auto-commit is disabled.
- [x] Service writes rows before committing source Kafka offsets.
- [x] Poison records are sent to DLQ, then committed to avoid infinite poison-message loops.
- [x] Validate transformer against a running Kafka/Cassandra stack after Cassandra code-137 issue is fixed.
- [x] Add finite `--max-messages` smoke-test mode.
- [x] Normalize MongoDB Debezium JSON-string documents before support-case mapping.
- [x] Configure Cassandra local datacenter and protocol version explicitly.

### CDCV2-008: Add data generator services

Priority: P1

Status: Done for active local sources

Scope:

- Generate realistic order, payment, inventory, and support events.
- Keep referential consistency across services.
- Simulate failures, refunds, SLA breaches, and stock movements.

Acceptance criteria:

- [x] Generator can run repeatedly for PostgreSQL, MySQL, and MongoDB.
- [x] Demo data creates visible dashboard changes.
- [x] Generator uses parameterized SQL or safe driver APIs.
- [ ] Add long-running mode with rates, skew, and failure scenario controls.
- [ ] Add Oracle inventory generator or a lightweight local replacement.

### CDCV2-009: Add Trino and dashboard UI

Priority: P1

Status: Mostly done

Scope:

- Configure Trino Cassandra catalog.
- Add SQL views for dashboard queries.
- Add a lightweight browser dashboard.
- Add Superset import bundle or documented setup as optional BI path.

Acceptance criteria:

- [x] Trino Cassandra catalog exists.
- [x] Trino startup fixed by setting `cassandra.load-policy.dc-aware.local-dc=datacenter1`.
- [x] Trino query against Cassandra tables revalidated after Cassandra runtime fix.
- [x] Dashboard SQL exists for revenue, payment health, stock movement, SLA, and order-to-cash.
- [x] Lightweight dashboard service exists under `dashboard`.
- [x] Dashboard container is wired into Compose on port `18090`.
- [x] Re-run dashboard data validation after root promotion.
- [ ] Superset import bundle or documented setup exists as optional BI path.

## P2 - Production Hardening

### CDCV2-010: Add observability stack

Priority: P2

Status: Initial implementation done

Scope:

- Prometheus.
- Grafana dashboards.
- Kafka Connect and Debezium JMX metrics.
- Pipeline freshness and DLQ alerts.

Acceptance criteria:

- [x] Project-owned metrics exporter exists under `observability/exporter`.
- [x] Exporter exposes Kafka Connect API availability, connector state, connector task state, dashboard API availability, dashboard snapshot freshness, and dashboard summary values.
- [x] Prometheus scrape config exists and is wired into Compose.
- [x] Starter Prometheus alert rules exist for Connect availability, connector/task state, dashboard API health, stale dashboard snapshots, and missing order facts.
- [x] Grafana datasource and dashboard provisioning exists.
- [x] CI validates exporter tests and Grafana dashboard JSON.
- [x] Transformer exposes processed message counters, DLQ counters, row counts, and Cassandra write latency.
- [x] Prometheus is configured to scrape transformer metrics in the local Compose stack.
- [x] Grafana includes transformer message-rate and Cassandra write-latency panels.
- [ ] Add Kafka consumer lag metrics.
- [ ] Add Debezium/JMX internals for source lag and connector throughput.

### CDCV2-011: Add config validation CLI

Priority: P2

Status: Initial implementation done

Scope:

- Validate connector JSON.
- Validate topic naming.
- Validate source-to-target mappings.
- Validate required secrets.

Acceptance criteria:

- [x] CI can run validation without starting Docker.
- [x] Bad config fails fast with actionable errors.
- [x] Required env vars, connector JSON shape, topic prefixes, placeholders, and active source coverage are checked.
- [x] Add CI workflow to run the validator automatically on push.

### CDCV2-012: Add cloud deployment templates

Priority: P2

Status: Not started

Scope:

- AWS MSK/MSK Connect option.
- GCP Datastream/Dataflow option.
- Datacenter Kubernetes option with Strimzi.

Acceptance criteria:

- [ ] Architecture docs include environment-specific deployment paths.
- [ ] Terraform or Helm skeleton exists.

### CDCV2-013: Add replay and resnapshot runbooks

Priority: P2

Status: Not started

Scope:

- Replay one topic to Cassandra.
- Resnapshot one table.
- Recover from lost source log position.
- Recover from bad transformation release.

Acceptance criteria:

- [ ] Runbooks are executable by an engineer who did not write the pipeline.

### CDCV2-014: Add security hardening

Priority: P2

Status: Not started

Scope:

- TLS plan.
- Kafka ACL plan.
- Secrets manager integration plan.
- PII classification and masking rules.

Acceptance criteria:

- [ ] No secrets are committed.
- [ ] Every connector has a least-privilege source user plan.
- [ ] PII fields are explicitly documented.

### CDCV2-015: Add production MongoDB authentication

Priority: P2

Status: Not started

Scope:

- Add replica set keyfile handling.
- Add dedicated Debezium MongoDB user.
- Add TLS and credential externalization.

Acceptance criteria:

- [x] Local no-auth Mongo mode is clearly separated from production mode through this explicit hardening ticket.
- [ ] Production MongoDB connector uses least-privilege credentials from a secret provider.

## Recommended Next Tickets

1. `CDCV2-009`: add Superset import bundle or documented setup so the dashboard is demo-ready.
2. `CDCV2-010B`: complete observability hardening with Kafka consumer lag and Debezium/JMX internals.
3. `CDCV2-011`: add config validation CLI for connector JSON, topic naming, required env vars, and source-to-target mapping coverage.
4. `CDCV2-013`: add replay/resnapshot runbooks using the replay flow validated on 2026-05-08.
5. `CDCV2-014`: add production security hardening: TLS, Kafka ACLs, secrets manager, source least privilege, and PII classification.
