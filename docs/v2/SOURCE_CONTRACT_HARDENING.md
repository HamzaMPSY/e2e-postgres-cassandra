# Source Contract Hardening

CDCV2-025 moves preventable bad data as close to the source as the demo stack can reasonably enforce it. Source constraints are not a replacement for transformer validation or dashboard quality gates; they are the first gate in a layered CDC control model.

## Control Layers

```text
source database constraints
  -> Debezium CDC contract
  -> transformer validation and business guardrails
  -> Cassandra serving tables
  -> dashboard quality gates and alerts
```

Use each layer for a different class of failure:

| Layer | Owns | Examples |
|---|---|---|
| Source constraints | Synchronous row/document invariants that the owning application can enforce before commit | Required keys, non-negative amounts, enum domains, valid document date types |
| Transformer validation | CDC envelope parsing, serving-schema requirements, cross-source timing, and business rules that need more context than one source row | Unknown event shape, impossible captured amount, overpayment against observed order total, missing serving dimensions |
| Dashboard quality gates | Detection after materialization and operational trust checks | Stale data, DLQ growth, raw bad facts in Cassandra, reconciliation failure |

## Local Demo Enforcement

MySQL billing uses `CHECK` constraints in `mysql/init.sql`:

- `payments.amount_cents >= 0`
- `refunds.amount_cents >= 0`
- `payment_status IN ('captured', 'failed', 'pending')`
- `payment_method IN ('card', 'wire', 'insurance')`
- `refund_reason IN ('duplicate_charge', 'returned_goods', 'contract_adjustment')`

MongoDB engagement uses a strict JSON schema validator in `mongo/init.js` for `support_tickets`:

- Required `ticket_id`, `customer_id`, `priority`, `status`, and `opened_at`.
- `ticket_id` and `customer_id` must be non-empty strings.
- `priority` and `status` must be known enum values.
- `opened_at` must be a BSON date.
- `sla_due_at` and `closed_at` may be BSON dates or `null`.

The `mongo-setup` service mounts and runs the committed `mongo/init.js` so local collection creation and `collMod` updates use the same validator.

## Data Contract Coverage

`contracts/cdc-data-contracts.json` declares source-side quality rules under `sourceQualityRules`. For quality-sensitive MySQL and Mongo sources, the validator checks both the contract metadata and the local DDL/schema implementation:

```bash
python tools/validate_contracts.py
```

The validator fails when:

- A required `sourceQualityRules` section is removed from billing payments, billing refunds, or support tickets.
- A MySQL rule declares `mysql-check` but the matching `CHECK` is missing or has a different enum domain.
- A Mongo rule declares `mongo-json-schema` but the `support_tickets` validator lacks the required field, BSON type, enum, or strict/error mode.

## Production Guidance

| Engine | Production source controls |
|---|---|
| PostgreSQL | Use `NOT NULL`, `CHECK`, `FOREIGN KEY` where ownership allows it, enum/domain types for stable value sets, and validated `ALTER TABLE ... ADD CONSTRAINT` rollouts for existing data. |
| MySQL 8+ | Use `NOT NULL`, enforced `CHECK`, reference tables for large enums, and online schema-change tooling for hot tables. Verify the exact server version because older MySQL releases parsed but ignored `CHECK`. |
| Oracle | Use `NOT NULL`, `CHECK`, `FOREIGN KEY`, virtual columns for normalized constraints when useful, and edition-based or phased constraint validation for large tables. |
| SQL Server | Use `NOT NULL`, `CHECK`, `FOREIGN KEY`, filtered indexes where appropriate, and `WITH CHECK` validation before trusting existing rows. |
| MongoDB | Use collection validators with `$jsonSchema`, strict/error validation for critical collections, unique indexes for business keys, and staged `validationLevel` changes when legacy documents exist. |

## Rollout Notes

Local `CREATE TABLE IF NOT EXISTS` changes only apply automatically to a fresh MySQL volume. Existing local stacks need either a volume reset or equivalent `ALTER TABLE ... ADD CONSTRAINT` statements. Mongo validation is idempotent because `mongo/init.js` creates the collection when missing and uses `collMod` when it already exists.

In production, never add hard source constraints blindly to dirty tables. First run profiling queries, backfill or quarantine bad rows, add the constraint in a non-blocking mode if the engine supports it, validate, then switch to enforcing mode.
