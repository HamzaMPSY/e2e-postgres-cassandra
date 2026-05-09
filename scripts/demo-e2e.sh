#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/demo-e2e.sh [options]

Runs a bounded local end-to-end CDC demo:
  Podman stack -> connector registration -> generator -> transformer smoke run
  -> Cassandra row-count checks -> dashboard API check -> JSON report.

Options:
  --env-file FILE                 Default: .env
  --report-file FILE              Default: artifacts/demo-report.json
  --max-events N                  Generator events. Default: 50.
  --rate-per-second N             Generator rate. Default: 5.
  --transformer-max-messages N    Transformer smoke read limit. Default: 500.
  --idle-timeout-seconds N        Transformer idle timeout. Default: 20.
  --timeout-seconds N             Wait timeout for services/data. Default: 300.
  --skip-start                    Do not run podman compose up.
  --skip-register-connectors      Do not register local connectors.
  --skip-generator                Do not run the generator.
  --skip-transformer              Do not run the bounded transformer smoke command.
  --dry-run                       Print commands without executing them.
  -h, --help                      Show help.

Prerequisites for a real run:
  cp .env.example .env
  python -m pip install -e generator
  envsubst and jq available for connector registration
USAGE
}

env_file=".env"
report_file="artifacts/demo-report.json"
max_events=50
rate_per_second=5
transformer_max_messages=500
idle_timeout_seconds=20
timeout_seconds=300
skip_start=false
skip_register_connectors=false
skip_generator=false
skip_transformer=false
dry_run=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      env_file="${2:?Missing value for --env-file}"
      shift 2
      ;;
    --report-file)
      report_file="${2:?Missing value for --report-file}"
      shift 2
      ;;
    --max-events)
      max_events="${2:?Missing value for --max-events}"
      shift 2
      ;;
    --rate-per-second)
      rate_per_second="${2:?Missing value for --rate-per-second}"
      shift 2
      ;;
    --transformer-max-messages)
      transformer_max_messages="${2:?Missing value for --transformer-max-messages}"
      shift 2
      ;;
    --idle-timeout-seconds)
      idle_timeout_seconds="${2:?Missing value for --idle-timeout-seconds}"
      shift 2
      ;;
    --timeout-seconds)
      timeout_seconds="${2:?Missing value for --timeout-seconds}"
      shift 2
      ;;
    --skip-start)
      skip_start=true
      shift
      ;;
    --skip-register-connectors)
      skip_register_connectors=true
      shift
      ;;
    --skip-generator)
      skip_generator=true
      shift
      ;;
    --skip-transformer)
      skip_transformer=true
      shift
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

positive_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

for value_name in max_events transformer_max_messages idle_timeout_seconds timeout_seconds; do
  value="${!value_name}"
  if ! positive_integer "$value"; then
    echo "--${value_name//_/-} must be a positive integer." >&2
    exit 2
  fi
done

if ! [[ "$rate_per_second" =~ ^[0-9]+([.][0-9]+)?$ ]] || [[ "$rate_per_second" == "0" ]]; then
  echo "--rate-per-second must be a positive number." >&2
  exit 2
fi

log() {
  printf '[demo] %s\n' "$*"
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

require_runtime() {
  require_command curl
  require_command podman
  require_command python
  if [[ "$skip_register_connectors" != true ]]; then
    require_command envsubst
    require_command jq
  fi
  if [[ "$skip_generator" != true ]]; then
    python - <<'PY'
import psycopg
import pymongo
import pymysql
PY
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
  echo "Create it with: cp .env.example .env" >&2
  exit 2
}

wait_http() {
  local name="$1"
  local url="$2"
  local deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$name is ready"
      return
    fi
    sleep 2
  done
  echo "Timed out waiting for $name at $url" >&2
  exit 1
}

connector_ready() {
  local name="$1"
  local status_json
  status_json="$(curl -fsS "http://localhost:18083/connectors/$name/status")"
  python - "$status_json" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
connector = payload.get("connector", {}).get("state")
tasks = [task.get("state") for task in payload.get("tasks", [])]
if connector == "RUNNING" and tasks and all(task == "RUNNING" for task in tasks):
    raise SystemExit(0)
raise SystemExit(1)
PY
}

wait_connectors() {
  local deadline=$((SECONDS + timeout_seconds))
  local connectors=(
    postgres-orders-local
    mysql-billing-local
    mongo-engagement-local
  )
  while (( SECONDS < deadline )); do
    local ready=true
    for connector in "${connectors[@]}"; do
      if ! connector_ready "$connector" >/dev/null 2>&1; then
        ready=false
        break
      fi
    done
    if [[ "$ready" == true ]]; then
      log "connectors are running"
      return
    fi
    sleep 3
  done
  echo "Timed out waiting for connectors to run." >&2
  exit 1
}

cassandra_count() {
  local table="$1"
  podman exec omnicare-cassandra cqlsh cassandra 9042 \
    -e "SELECT count(*) FROM omnicare_dashboard.$table;" \
    | awk '/^[[:space:]]*[0-9]+[[:space:]]*$/ {gsub(/[[:space:]]/, "", $0); print $0; exit}'
}

wait_cassandra_count() {
  local table="$1"
  local deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    local count
    count="$(cassandra_count "$table" || true)"
    if [[ "$count" =~ ^[1-9][0-9]*$ ]]; then
      printf '%s' "$count"
      return
    fi
    sleep 3
  done
  echo "Timed out waiting for Cassandra table $table to contain rows." >&2
  exit 1
}

dashboard_has_data() {
  local snapshot_file="$1"
  curl -fsS http://localhost:18090/api/dashboard > "$snapshot_file"
  python - "$snapshot_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
summary = payload.get("summary", {})
if int(summary.get("orderLines") or 0) > 0 and payload.get("revenueByDay"):
    raise SystemExit(0)
raise SystemExit(1)
PY
}

wait_dashboard_data() {
  local snapshot_file="$1"
  local deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    if dashboard_has_data "$snapshot_file"; then
      log "dashboard API has non-empty data"
      return
    fi
    sleep 3
  done
  echo "Timed out waiting for dashboard API data." >&2
  exit 1
}

write_report() {
  local snapshot_file="$1"
  local order_lines="$2"
  local payments="$3"
  local support_cases="$4"
  local inventory_movements="$5"
  local report_dir
  report_dir="$(dirname "$report_file")"
  mkdir -p "$report_dir"
  python - "$snapshot_file" "$report_file" \
    "$order_lines" "$payments" "$support_cases" "$inventory_movements" <<'PY'
import json
import sys
import time

snapshot_path, report_path = sys.argv[1], sys.argv[2]
counts = {
    "fact_order_line_by_day": int(sys.argv[3]),
    "fact_payment_by_day": int(sys.argv[4]),
    "fact_support_case_by_customer": int(sys.argv[5]),
    "fact_inventory_movement_by_product": int(sys.argv[6]),
}
with open(snapshot_path, encoding="utf-8") as handle:
    dashboard = json.load(handle)
report = {
    "generatedAt": int(time.time()),
    "status": "passed",
    "checks": {
        "cassandraRowCounts": counts,
        "dashboardSummary": dashboard.get("summary", {}),
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

if [[ "$dry_run" != true ]]; then
  require_runtime
fi
load_env

postgres_dsn="${POSTGRES_DSN:-postgresql://${POSTGRES_USER:-orders_cdc_demo}:${POSTGRES_PASSWORD:-change_me_orders}@localhost:15432/${POSTGRES_DB:-orders}}"
mongo_uri="${MONGO_URI:-mongodb://localhost:27017/engagement?directConnection=true}"
demo_group_id="demo-e2e-$(date -u +%Y%m%dT%H%M%SZ)"

if [[ "$skip_start" != true ]]; then
  log "starting local stack"
  run podman compose --env-file "$env_file" -f docker-compose.yaml up -d
fi

if [[ "$dry_run" == true ]]; then
  log "dry-run complete"
  run env ENV_FILE="$env_file" CONNECT_URL=http://localhost:18083 scripts/register-connectors.sh
  run_shell "cd generator && PYTHONPATH=src POSTGRES_DSN='$postgres_dsn' MYSQL_HOST=localhost MYSQL_PORT=13306 MYSQL_DATABASE='${MYSQL_DATABASE:-billing}' MYSQL_USER='${MYSQL_USER:-billing_cdc_demo}' MYSQL_PASSWORD='${MYSQL_PASSWORD:-change_me_billing}' MONGO_URI='$mongo_uri' python -m omnicare_generator.main --max-events '$max_events' --rate-per-second '$rate_per_second' --failure-rate 0.20 --refund-rate 0.15 --sla-breach-rate 0.20"
  run podman compose --env-file "$env_file" -f docker-compose.yaml exec -T \
    -e KAFKA_GROUP_ID="$demo_group_id" \
    -e CDC_SOURCE_TOPICS="$active_topics" \
    -e TRANSFORMER_METRICS_ENABLED=false \
    transformer python -m omnicare_cdc.main \
    --max-messages "$transformer_max_messages" \
    --idle-timeout-seconds "$idle_timeout_seconds"
  printf '+ verify Cassandra row counts and dashboard API, then write %q\n' "$report_file"
  exit 0
fi

wait_http "Kafka Connect" "http://localhost:18083/connectors"
wait_http "dashboard" "http://localhost:18090/health"

if [[ "$skip_register_connectors" != true ]]; then
  log "registering local connectors"
  run env ENV_FILE="$env_file" CONNECT_URL=http://localhost:18083 scripts/register-connectors.sh
  wait_connectors
fi

if [[ "$skip_generator" != true ]]; then
  log "generating demo source data"
  run_shell "cd generator && PYTHONPATH=src POSTGRES_DSN='$postgres_dsn' MYSQL_HOST=localhost MYSQL_PORT=13306 MYSQL_DATABASE='${MYSQL_DATABASE:-billing}' MYSQL_USER='${MYSQL_USER:-billing_cdc_demo}' MYSQL_PASSWORD='${MYSQL_PASSWORD:-change_me_billing}' MONGO_URI='$mongo_uri' python -m omnicare_generator.main --max-events '$max_events' --rate-per-second '$rate_per_second' --failure-rate 0.20 --refund-rate 0.15 --sla-breach-rate 0.20"
fi

if [[ "$skip_transformer" != true ]]; then
  log "running bounded transformer smoke consumer"
  run podman compose --env-file "$env_file" -f docker-compose.yaml exec -T \
    -e KAFKA_GROUP_ID="$demo_group_id" \
    -e CDC_SOURCE_TOPICS="$active_topics" \
    -e TRANSFORMER_METRICS_ENABLED=false \
    transformer python -m omnicare_cdc.main \
    --max-messages "$transformer_max_messages" \
    --idle-timeout-seconds "$idle_timeout_seconds"
fi

log "verifying Cassandra serving tables"
order_lines="$(wait_cassandra_count fact_order_line_by_day)"
payments="$(wait_cassandra_count fact_payment_by_day)"
support_cases="$(wait_cassandra_count fact_support_case_by_customer)"
inventory_movements="$(wait_cassandra_count fact_inventory_movement_by_product)"

snapshot_file="$(mktemp)"
trap 'rm -f "$snapshot_file"' EXIT
wait_dashboard_data "$snapshot_file"
write_report "$snapshot_file" "$order_lines" "$payments" "$support_cases" "$inventory_movements"

log "demo passed"
log "report: $report_file"
