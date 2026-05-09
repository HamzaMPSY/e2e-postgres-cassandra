# Schema Governance and Data Contracts

CDCV2-019 adds a committed schema governance contract for the CDC platform:

```text
Source database object
  -> Debezium topic contract
  -> transformer mapper contract
  -> Cassandra serving-table contract
```

The contract lives in `contracts/cdc-data-contracts.json`. It is intentionally JSON so CI, deployment pipelines, and interview demos can inspect the same artifact.

## What The Contract Covers

For every captured source table or collection, the contract declares:

- Source owner application and database engine.
- Source data collection name.
- Local and production topic prefixes.
- Natural key fields.
- Required `after` fields for insert/update/read events.
- Materialization status: `dimension`, `fact`, or `captured-only`.
- Cassandra target tables, when materialized.
- PII or confidential-data classification.

For every Cassandra target table, it declares:

- Table type.
- Primary key columns.
- Required serving columns.

The global compatibility mode is `BACKWARD_TRANSITIVE`. In practice, additive nullable fields are safe, but field removal, rename, type changes, and primary-key changes require a versioned migration plan.

## Captured-Only Streams

Some streams are intentionally captured but not yet materialized into Cassandra:

- `public.orders`
- `billing.invoices`
- `engagement.customer_events`
- `ERP_APP.SUPPLIERS`

They are kept in the contract instead of ignored. That makes the design decision explicit: Kafka may retain them for replay or future consumers, but the dashboard transformer does not currently write them to star-schema tables.

## CI Validation

Run:

```bash
python tools/validate_contracts.py
```

The validator checks that:

- Every connector table or collection has a source contract, excluding Debezium signal tables.
- Every materialized source has a transformer `_MAPPERS` entry.
- Every materialized target table has a target contract.
- Every target contract exists in `cassandra/schema.cql`.
- Required target columns and primary-key columns exist in Cassandra.
- Topic prefixes match the project naming contract.
- Key fields are included in required source fields.

CI runs this validation on every push and pull request.

## Change Review Rules

Use this checklist before changing a source schema, connector include list, transformer mapping, or Cassandra table:

- Additive nullable source field: update the contract if the field becomes part of the published CDC contract.
- New materialized source table: add a source contract, transformer mapper, Cassandra target contract, and tests.
- Captured but not materialized source table: add a `captured-only` source contract and explain the future consumer or retention reason.
- Field rename: treat as add-new plus deprecate-old; do not silently rename fields in place.
- Type change: require compatibility review and replay testing.
- Primary key change: require a new target-table strategy because Cassandra table keys are part of the serving API.
- PII classification change: update `docs/v2/security-controls.json` and masking policy before deploy.
