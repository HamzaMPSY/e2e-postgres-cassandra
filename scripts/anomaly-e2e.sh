#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/anomaly-e2e.sh [options]

Runs a bounded anomaly CDC test:
  source constraint rejects -> accepted anomaly inserts -> transformer smoke run
  -> DLQ/Cassandra/dashboard checks -> JSON report.

Options:
  --env-file FILE                 Default: .env
  --report-file FILE              Default: artifacts/anomaly-report.json
  --transformer-max-messages N    Transformer smoke read limit. Default: 500.
  --idle-timeout-seconds N        Transformer idle timeout. Default: 20.
  --timeout-seconds N             Wait timeout. Default: 300.
  --skip-start                    Do not run podman compose up.
  --skip-register-connectors      Do not register local connectors.
  --cleanup                       Delete anomaly source rows before inserting.
  --dry-run                       Print commands without executing them.
  -h, --help                      Show help.
USAGE
}

env_file=".env"
report_file="artifacts/anomaly-report.json"
transformer_max_messages=500
idle_timeout_seconds=20
timeout_seconds=300
skip_start=false
skip_register_connectors=false
cleanup=false
dry_run=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) env_file="${2:?Missing value for --env-file}"; shift 2 ;;
    --report-file) report_file="${2:?Missing value for --report-file}"; shift 2 ;;
    --transformer-max-messages) transformer_max_messages="${2:?Missing value}"; shift 2 ;;
    --idle-timeout-seconds) idle_timeout_seconds="${2:?Missing value}"; shift 2 ;;
    --timeout-seconds) timeout_seconds="${2:?Missing value}"; shift 2 ;;
    --skip-start) skip_start=true; shift ;;
    --skip-register-connectors) skip_register_connectors=true; shift ;;
    --cleanup) cleanup=true; shift ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

positive_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

for value_name in transformer_max_messages idle_timeout_seconds timeout_seconds; do
  value="${!value_name}"
  if ! positive_integer "$value"; then
    echo "--${value_name//_/-} must be a positive integer." >&2
    exit 2
  fi
done

log() {
  printf '[anomaly] %s\n' "$*"
}

run() {
  if [[ "$dry_run" == true ]]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    return
  fi
  "$@"
}

run_shell() {
  if [[ "$dry_run" == true ]]; then
    printf '+ %s\n' "$*"
    return
  fi
  bash -lc "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

load_env() {
  if [[ -f "$env_file" ]]; then
    set -a
    source "$env_file"
    set +a
    return
  fi
  if [[ "$dry_run" == true ]]; then
    return
  fi
  echo "Missing env file: $env_file" >&2
  exit 2
}

wait_http() {
  local name="$1"
  local url="$2"
  local deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
      log "$name is ready"
      return
    fi
    sleep 2
  done
  echo "Timed out waiting for $name at $url" >&2
  exit 1
}

cassandra_count() {
  local table="$1"
  local output
  if ! output="$(podman exec omnicare-cassandra cqlsh cassandra 9042 \
    -e "SELECT count(*) FROM omnicare_dashboard.$table;" 2>/dev/null)"; then
    printf '0\n'
    return
  fi
  awk '/^[[:space:]]*[0-9]+[[:space:]]*$/ {gsub(/[[:space:]]/, "", $0); print $0; found=1; exit} END {if (!found) print 0}' <<<"$output"
}

cassandra_filtered_count() {
  local table="$1"
  local where_clause="$2"
  local output
  if ! output="$(podman exec omnicare-cassandra cqlsh cassandra 9042 \
    -e "SELECT count(*) FROM omnicare_dashboard.$table WHERE $where_clause ALLOW FILTERING;" 2>/dev/null)"; then
    printf '0\n'
    return
  fi
  awk '/^[[:space:]]*[0-9]+[[:space:]]*$/ {gsub(/[[:space:]]/, "", $0); print $0; found=1; exit} END {if (!found) print 0}' <<<"$output"
}

dlq_count() {
  podman exec omnicare-kafka kafka-console-consumer \
    --bootstrap-server kafka:9092 \
    --topic dlq.local.omnicare.transformer \
    --from-beginning \
    --timeout-ms 5000 \
    2>/dev/null \
    | awk 'NF {count++} END {print count + 0}'
}

cleanup_cassandra_anomaly_rows() {
  local payment_deletes
  local support_deletes

  payment_deletes="$(
    podman exec omnicare-cassandra cqlsh cassandra 9042 \
      -e "SELECT payment_day, fact_id, payment_id FROM omnicare_dashboard.fact_payment_by_day;" \
      | awk -F'|' '
          function trim(value) {
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            return value
          }
          {
            payment_day = trim($1)
            fact_id = trim($2)
            payment_id = trim($3)
            if (payment_id ~ /^PAY-ANOM-/) {
              printf "DELETE FROM omnicare_dashboard.fact_payment_by_day WHERE payment_day = '\''%s'\'' AND fact_id = '\''%s'\'';\n", payment_day, fact_id
            }
          }
        '
  )"
  if [[ -n "$payment_deletes" ]]; then
    printf '%s\n' "$payment_deletes" | podman exec -i omnicare-cassandra cqlsh cassandra 9042
  fi

  support_deletes="$(
    podman exec omnicare-cassandra cqlsh cassandra 9042 \
      -e "SELECT customer_id, opened_day, fact_id, ticket_id FROM omnicare_dashboard.fact_support_case_by_customer;" \
      | awk -F'|' '
          function trim(value) {
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            return value
          }
          {
            customer_id = trim($1)
            opened_day = trim($2)
            fact_id = trim($3)
            ticket_id = trim($4)
            if (ticket_id ~ /^TCK-ANOM-/) {
              printf "DELETE FROM omnicare_dashboard.fact_support_case_by_customer WHERE customer_id = '\''%s'\'' AND opened_day = '\''%s'\'' AND fact_id = '\''%s'\'';\n", customer_id, opened_day, fact_id
            }
          }
        '
  )"
  if [[ -n "$support_deletes" ]]; then
    printf '%s\n' "$support_deletes" | podman exec -i omnicare-cassandra cqlsh cassandra 9042
  fi
}

expect_failure() {
  local label="$1"
  shift
  log "expecting source reject: $label"
  if [[ "$dry_run" == true ]]; then
    run "$@"
    return
  fi
  if "$@" >/tmp/omnicare-anomaly-reject.out 2>&1; then
    cat /tmp/omnicare-anomaly-reject.out >&2
    echo "Expected command to fail: $label" >&2
    exit 1
  fi
}

write_report() {
  local snapshot_file="$1"
  local report_dir
  report_dir="$(dirname "$report_file")"
  mkdir -p "$report_dir"
  python - "$snapshot_file" "$report_file" \
    "$before_payments" "$after_payments" "$before_support" "$after_support" \
    "$before_dlq" "$after_dlq" \
    "$accepted_payment_count" "$bad_payment_count" "$bad_support_count" <<'PY'
import json
import sys
import time

snapshot_path, report_path = sys.argv[1], sys.argv[2]
with open(snapshot_path, encoding="utf-8") as handle:
    dashboard = json.load(handle)
report = {
    "generatedAt": int(time.time()),
    "status": "passed",
    "checks": {
        "sourceRejects": {
            "postgresNegativeOrderQuantity": "rejected",
            "postgresNullProductId": "rejected",
            "mysqlNullAmount": "rejected",
        },
        "cassandraDeltas": {
            "fact_payment_by_day": int(sys.argv[4]) - int(sys.argv[3]),
            "fact_support_case_by_customer": int(sys.argv[6]) - int(sys.argv[5]),
        },
        "dlqDelta": int(sys.argv[8]) - int(sys.argv[7]),
        "anomalyRecordCounts": {
            "acceptedPendingPayment": int(sys.argv[9]),
            "badCapturedPayments": int(sys.argv[10]),
            "badSupportTickets": int(sys.argv[11]),
        },
        "dashboardSummary": dashboard.get("summary", {}),
        "dataQuality": dashboard.get("dataQuality", {}),
    },
    "dashboardUrl": "http://localhost:18090",
    "grafanaUrl": "http://localhost:13000",
    "prometheusUrl": "http://localhost:19090",
}
with open(report_path, "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
}

active_topics="cdc.local.omnicare.postgres.public.customers,cdc.local.omnicare.postgres.public.order_items,cdc.local.omnicare.postgres.public.products,cdc.local.omnicare.postgres.public.stock_movements,cdc.local.omnicare.mysql.billing.payments,cdc.local.omnicare.mysql.billing.refunds,cdc.local.omnicare.mongo.engagement.support_tickets"
anomaly_run_id="ANOM-$(date -u +%Y%m%dT%H%M%SZ)-$$"

if [[ "$dry_run" != true ]]; then
  require_command curl
  require_command podman
  require_command python
  if [[ "$skip_register_connectors" != true ]]; then
    require_command envsubst
    require_command jq
  fi
fi
load_env

if [[ "$skip_start" != true ]]; then
  log "starting local stack"
  run podman compose --env-file "$env_file" -f docker-compose.yaml up -d
fi

if [[ "$dry_run" == true ]]; then
  log "dry-run complete"
  if [[ "$skip_register_connectors" != true ]]; then
    run env ENV_FILE="$env_file" CONNECT_URL=http://localhost:18083 scripts/register-connectors.sh
  fi
  printf '+ verify source rejects for PostgreSQL/MySQL constraints\n'
  printf '+ insert accepted anomaly rows into MySQL payments and MongoDB support_tickets\n'
  run podman compose --env-file "$env_file" -f docker-compose.yaml run --rm --no-deps \
    -e KAFKA_GROUP_ID="anomaly-e2e-dry-run" \
    -e CDC_SOURCE_TOPICS="$active_topics" \
    -e TRANSFORMER_METRICS_ENABLED=false \
    transformer python -m omnicare_cdc.main \
    --max-messages "$transformer_max_messages" \
    --idle-timeout-seconds "$idle_timeout_seconds"
  printf '+ verify DLQ/Cassandra/dashboard, run tools/quality_gate.py, then write %q\n' "$report_file"
  exit 0
fi

wait_http "Kafka Connect" "http://localhost:18083/connectors"
wait_http "dashboard" "http://localhost:18090/health"

if [[ "$skip_register_connectors" != true ]]; then
  log "registering local connectors"
  run env ENV_FILE="$env_file" CONNECT_URL=http://localhost:18083 scripts/register-connectors.sh
fi

if [[ "$cleanup" == true ]]; then
  log "cleaning source anomaly rows"
  run podman exec omnicare-mysql-billing mysql -u"${MYSQL_USER:-billing_cdc_demo}" \
    -p"${MYSQL_PASSWORD:-change_me_billing}" "${MYSQL_DATABASE:-billing}" \
    -e "DELETE FROM payments WHERE payment_id LIKE 'PAY-ANOM-%';"
  run podman exec omnicare-mongo-engagement mongosh \
    "mongodb://localhost:27017/engagement?replicaSet=rs0" \
    --quiet --eval 'db.support_tickets.deleteMany({$or:[{ticket_id:/^TCK-ANOM-/},{customer_id:/^mongo-/}]});'
  log "cleaning Cassandra anomaly facts"
  cleanup_cassandra_anomaly_rows
fi

before_payments="$(cassandra_count fact_payment_by_day || printf '0')"
before_support="$(cassandra_count fact_support_case_by_customer || printf '0')"
before_dlq="$(dlq_count || printf '0')"

expect_failure "postgres negative order quantity" \
  podman exec omnicare-postgres-orders psql -U "${POSTGRES_USER:-orders_cdc_demo}" \
  -d "${POSTGRES_DB:-orders}" -v ON_ERROR_STOP=1 \
  -c "WITH refs AS (SELECT order_id, customer_id, product_id, channel, order_status, ordered_at FROM order_items LIMIT 1) INSERT INTO order_items (order_item_id, order_id, customer_id, product_id, channel, order_status, ordered_at, quantity, unit_price_cents) SELECT '00000000-0000-4000-8000-00000000a101'::uuid, order_id, customer_id, product_id, channel, order_status, ordered_at, -3, 1000 FROM refs;"

expect_failure "postgres null product id" \
  podman exec omnicare-postgres-orders psql -U "${POSTGRES_USER:-orders_cdc_demo}" \
  -d "${POSTGRES_DB:-orders}" -v ON_ERROR_STOP=1 \
  -c "WITH refs AS (SELECT order_id, customer_id, channel, order_status, ordered_at FROM order_items LIMIT 1) INSERT INTO order_items (order_item_id, order_id, customer_id, product_id, channel, order_status, ordered_at, quantity, unit_price_cents) SELECT '00000000-0000-4000-8000-00000000a102'::uuid, order_id, customer_id, NULL, channel, order_status, ordered_at, 1, 1000 FROM refs;"

log "inserting accepted MySQL anomalies"
run podman exec omnicare-mysql-billing mysql -u"${MYSQL_USER:-billing_cdc_demo}" \
  -p"${MYSQL_PASSWORD:-change_me_billing}" "${MYSQL_DATABASE:-billing}" \
  -e "INSERT INTO payments (payment_id, invoice_id, order_id, customer_id, payment_status, payment_method, amount_cents, paid_at) SELECT 'PAY-ANOM-OVERPAY-${anomaly_run_id}', invoice_id, order_id, customer_id, 'captured', 'card', 99999999, NOW() FROM payments LIMIT 1; INSERT INTO payments (payment_id, invoice_id, order_id, customer_id, payment_status, payment_method, amount_cents, paid_at) SELECT 'PAY-ANOM-NEGATIVE-${anomaly_run_id}', invoice_id, order_id, customer_id, 'captured', 'wire', -12345, NOW() FROM payments LIMIT 1; INSERT INTO payments (payment_id, invoice_id, order_id, customer_id, payment_status, payment_method, amount_cents, paid_at) SELECT 'PAY-ANOM-NULLPAID-${anomaly_run_id}', invoice_id, order_id, customer_id, 'pending', 'insurance', 7777, NULL FROM payments LIMIT 1;"

expect_failure "mysql null amount" \
  podman exec omnicare-mysql-billing mysql -u"${MYSQL_USER:-billing_cdc_demo}" \
  -p"${MYSQL_PASSWORD:-change_me_billing}" "${MYSQL_DATABASE:-billing}" \
  -e "INSERT INTO payments (payment_id, invoice_id, order_id, customer_id, payment_status, payment_method, amount_cents, paid_at) SELECT CONCAT('PAY-ANOM-NULLAMOUNT-', UUID()), invoice_id, order_id, customer_id, 'captured', 'card', NULL, NOW() FROM payments LIMIT 1;"

log "inserting accepted Mongo anomalies"
run podman exec omnicare-mongo-engagement mongosh \
  "mongodb://localhost:27017/engagement?replicaSet=rs0" \
  --quiet --eval "const now = new Date(); const runId = '${anomaly_run_id}'; db.support_tickets.insertMany([{ ticket_id: 'TCK-ANOM-NULL-CUSTOMER-' + runId, customer_id: null, priority: null, status: null, opened_at: now, sla_due_at: null, closed_at: null }, { customer_id: 'mongo-missing-ticket-' + runId, priority: 'critical', status: 'open', opened_at: now, sla_due_at: null, closed_at: null }, { ticket_id: 'TCK-ANOM-BAD-DATE-' + runId, customer_id: 'mongo-bad-date-' + runId, priority: 'high', status: 'open', opened_at: 'not-a-date', sla_due_at: null, closed_at: null }]);"

group_id="anomaly-e2e-$(date -u +%Y%m%dT%H%M%SZ)"
log "running bounded transformer anomaly consumer"
run podman compose --env-file "$env_file" -f docker-compose.yaml run --rm --no-deps \
  -e KAFKA_GROUP_ID="$group_id" \
  -e CDC_SOURCE_TOPICS="$active_topics" \
  -e TRANSFORMER_METRICS_ENABLED=false \
  transformer \
  python -m omnicare_cdc.main \
  --max-messages "$transformer_max_messages" \
  --idle-timeout-seconds "$idle_timeout_seconds"

after_payments="$(cassandra_count fact_payment_by_day || printf '0')"
after_support="$(cassandra_count fact_support_case_by_customer || printf '0')"
after_dlq="$(dlq_count || printf '0')"

payment_delta=$((after_payments - before_payments))
support_delta=$((after_support - before_support))
dlq_delta=$((after_dlq - before_dlq))
accepted_payment_count="$(cassandra_filtered_count fact_payment_by_day "payment_id = 'PAY-ANOM-NULLPAID-${anomaly_run_id}'" || printf '0')"
bad_overpay_count="$(cassandra_filtered_count fact_payment_by_day "payment_id = 'PAY-ANOM-OVERPAY-${anomaly_run_id}'" || printf '0')"
bad_negative_count="$(cassandra_filtered_count fact_payment_by_day "payment_id = 'PAY-ANOM-NEGATIVE-${anomaly_run_id}'" || printf '0')"
bad_support_null_count="$(cassandra_filtered_count fact_support_case_by_customer "ticket_id = 'TCK-ANOM-NULL-CUSTOMER-${anomaly_run_id}'" || printf '0')"
bad_support_date_count="$(cassandra_filtered_count fact_support_case_by_customer "ticket_id = 'TCK-ANOM-BAD-DATE-${anomaly_run_id}'" || printf '0')"
bad_payment_count=$((bad_overpay_count + bad_negative_count))
bad_support_count=$((bad_support_null_count + bad_support_date_count))

if (( accepted_payment_count != 1 )); then
  echo "Expected exactly one accepted pending payment anomaly, got $accepted_payment_count." >&2
  exit 1
fi
if (( bad_payment_count > 0 )); then
  echo "Expected bad captured payment anomalies to stay out of Cassandra, got $bad_payment_count." >&2
  exit 1
fi
if (( bad_support_count > 0 )); then
  echo "Expected no malformed support anomalies in Cassandra, got $bad_support_count." >&2
  exit 1
fi
if (( dlq_delta < 4 )); then
  echo "Expected at least four anomaly DLQ records, got $dlq_delta." >&2
  exit 1
fi

snapshot_file="$(mktemp)"
trap 'rm -f "$snapshot_file"' EXIT
run curl -fsS http://localhost:18090/api/dashboard -o "$snapshot_file"
run python tools/quality_gate.py \
  --snapshot-file "$snapshot_file" \
  --max-snapshot-age-seconds "$timeout_seconds"
write_report "$snapshot_file"

log "anomaly test passed"
log "report: $report_file"
