# Data Quality and Reconciliation Gates

CDCV2-020 adds operational quality gates around the dashboard-serving model. The goal is to catch bad CDC outcomes after the pipeline technically runs but before a dashboard is trusted.

## Runtime Quality Report

`GET /api/dashboard` now includes a `dataQuality` object:

```json
{
  "overallStatus": "pass",
  "maxEventAgeSeconds": 86400,
  "checks": [
    {
      "name": "dashboard_queries_ok",
      "status": "pass"
    }
  ]
}
```

Checks:

- `dashboard_queries_ok`: dashboard SQL queries must not return partial error rows.
- `non_negative_row_counts`: aggregate row counts must not be negative.
- `order_payment_reconciliation`: captured payments minus refunds must not exceed ordered revenue, and order open amounts must not go negative.
- `serving_payment_amounts_valid`: raw payment and refund facts in Cassandra must not contain negative source amounts.
- `serving_required_dimensions_present`: serving facts must keep required order, payment, support, and inventory dimensions populated.
- `serving_enum_values_known`: serving facts must use known status, method, priority, channel, reason, and movement-type values.
- `dlq_quarantine_thresholds`: transformer DLQ and validation reject counters must stay within configured thresholds when transformer metrics are available.
- `pipeline_event_freshness`: materialized events must be inside `DASHBOARD_FRESHNESS_MAX_AGE_SECONDS`.

Default freshness window:

```text
86400 seconds
```

Default DLQ/quarantine thresholds:

```text
DASHBOARD_DLQ_MAX_RECORDS=0
DASHBOARD_QUARANTINE_MAX_RECORDS=0
```

For checks that should warn instead of fail in a given environment, set a comma-separated list:

```text
DASHBOARD_QUALITY_WARNING_CHECKS=dlq_quarantine_thresholds
```

The CLI still exits non-zero for warnings unless `--allow-warnings` is used.

## CLI Gate

Validate a live dashboard:

```bash
python tools/quality_gate.py --dashboard-url http://localhost:18090
```

Validate a saved snapshot:

```bash
python tools/quality_gate.py --snapshot-file artifacts/dashboard-snapshot.json
```

The command exits non-zero on failed checks, stale snapshots, missing `dataQuality`, or warnings unless `--allow-warnings` is set.

## Demo Harness Gate

`scripts/demo-e2e.sh` now runs the quality gate after the dashboard returns non-empty data and before writing `artifacts/demo-report.json`. The report embeds the quality output under:

```text
checks.dataQuality
```

## Anomaly Harness Gate

`scripts/anomaly-e2e.sh` challenges the pipeline with bad source rows and accepted semantic anomalies before it runs the dashboard quality gate. It verifies that source constraints reject impossible rows, transformer validation quarantines malformed facts, and business guardrails keep bad captured payment facts out of Cassandra.

Default report path:

```text
artifacts/anomaly-report.json
```

See `docs/v2/ANOMALY_TESTING.md` for the scenario list and pass criteria.

## Observability

The metrics exporter emits:

```text
omnicare_data_quality_overall_status{status="pass|warn|fail"}
omnicare_data_quality_check_passed{check="...",status="..."}
omnicare_data_quality_check_status{check="...",status="pass|warn|fail"}
omnicare_data_quality_check_detail_value{check="...",metric="..."}
omnicare_quality_dlq_records_total
omnicare_quality_quarantine_records_total
```

Prometheus alert rules fail fast on `overallStatus=fail`, warn on sustained `overallStatus=warn`, and warn immediately when DLQ or transformer validation reject counters increase.

## Transformer Guardrails

The transformer rejects invalid star rows before Cassandra writes. Financial guardrails are config-driven:

```text
MAX_PAYMENT_AMOUNT_CENTS=10000000
PAYMENT_OVERPAY_TOLERANCE_CENTS=0
REFERENCE_VALIDATION_MODE=deferred
```

- `MAX_PAYMENT_AMOUNT_CENTS` quarantines impossible captured payment amounts before they pollute serving tables.
- `PAYMENT_OVERPAY_TOLERANCE_CENTS` is used when a matching order total has already been observed in the transformer process.
- `REFERENCE_VALIDATION_MODE=deferred` avoids false rejects when MySQL payment CDC arrives before Postgres order CDC. Use `strict` only when the deployment guarantees order/customer facts are available before payments or has a warm reference cache.

## Production Notes

These gates are intentionally deterministic and dashboard-focused. In a real production rollout, add source-specific controls too:

- Source row count vs. Kafka event count by capture window.
- Kafka topic count vs. Cassandra write count by source position.
- DLQ count by source topic and deployment version.
- Per-source freshness SLOs instead of one global dashboard window.
- Reconciliation tolerance windows for asynchronous payments and refunds.
- Environment-specific rule severity. For example, strict production can fail on any DLQ growth, while a test environment can downgrade known chaos-test rules to warnings.
