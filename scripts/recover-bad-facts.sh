#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/recover-bad-facts.sh [scope options] --yes [options]

Deletes matching local Cassandra serving facts and writes a recovery report.

Scope options, at least one required:
  --payment-id-prefix PREFIX      Delete fact_payment_by_day rows by payment_id prefix.
  --refund-id-prefix PREFIX       Delete fact_refund_by_day rows by refund_id prefix.
  --ticket-id-prefix PREFIX       Delete fact_support_case_by_customer rows by ticket_id prefix.
  --order-item-id-prefix PREFIX   Delete fact_order_line_by_day rows by order_item_id prefix.
  --movement-id-prefix PREFIX     Delete inventory fact rows by movement_id prefix.
  --source-position POSITION      Delete rows with this exact source_position. Can repeat.

Safety and output:
  --yes                           Required for live deletes.
  --dry-run                       Print resolved plan without querying or deleting.
  --report-file FILE              Default: artifacts/recovery-report.json.
  --dashboard-url URL             Default: http://localhost:18090.
  --max-snapshot-age-seconds N    Default: 300.
  --skip-dashboard                Do not capture dashboard quality before/after.
  -h, --help                      Show help.

Local Cassandra defaults:
  CASSANDRA_CONTAINER=omnicare-cassandra
  CASSANDRA_HOST=cassandra
  CASSANDRA_PORT=9042
  CASSANDRA_KEYSPACE=omnicare_dashboard
USAGE
}

payment_id_prefix=""
refund_id_prefix=""
ticket_id_prefix=""
order_item_id_prefix=""
movement_id_prefix=""
source_positions=()
report_file="artifacts/recovery-report.json"
dashboard_url="http://localhost:18090"
max_snapshot_age_seconds=300
skip_dashboard=false
dry_run=false
confirm=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --payment-id-prefix) payment_id_prefix="${2:?Missing value for --payment-id-prefix}"; shift 2 ;;
    --refund-id-prefix) refund_id_prefix="${2:?Missing value for --refund-id-prefix}"; shift 2 ;;
    --ticket-id-prefix) ticket_id_prefix="${2:?Missing value for --ticket-id-prefix}"; shift 2 ;;
    --order-item-id-prefix) order_item_id_prefix="${2:?Missing value for --order-item-id-prefix}"; shift 2 ;;
    --movement-id-prefix) movement_id_prefix="${2:?Missing value for --movement-id-prefix}"; shift 2 ;;
    --source-position) source_positions+=("${2:?Missing value for --source-position}"); shift 2 ;;
    --report-file) report_file="${2:?Missing value for --report-file}"; shift 2 ;;
    --dashboard-url) dashboard_url="${2:?Missing value for --dashboard-url}"; shift 2 ;;
    --max-snapshot-age-seconds) max_snapshot_age_seconds="${2:?Missing value for --max-snapshot-age-seconds}"; shift 2 ;;
    --skip-dashboard) skip_dashboard=true; shift ;;
    --dry-run) dry_run=true; shift ;;
    --yes) confirm=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

positive_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

require_scope() {
  if [[ -z "$payment_id_prefix" \
    && -z "$refund_id_prefix" \
    && -z "$ticket_id_prefix" \
    && -z "$order_item_id_prefix" \
    && -z "$movement_id_prefix" \
    && ${#source_positions[@]} -eq 0 ]]; then
    echo "Missing cleanup scope. Pass a prefix or --source-position." >&2
    exit 2
  fi
}

validate_prefix() {
  local label="$1"
  local value="$2"
  if [[ -n "$value" && ${#value} -lt 6 ]]; then
    echo "$label must be at least 6 characters to avoid broad deletes." >&2
    exit 2
  fi
}

log() {
  printf '[recovery] %s\n' "$*"
}

cql_escape() {
  printf "%s" "$1" | sed "s/'/''/g"
}

cqlsh_exec() {
  podman exec "${CASSANDRA_CONTAINER:-omnicare-cassandra}" \
    cqlsh "${CASSANDRA_HOST:-cassandra}" "${CASSANDRA_PORT:-9042}" "$@"
}

collect_prefix_deletes() {
  local table="$1"
  local id_column="$2"
  local prefix="$3"
  local select_columns="$4"
  local output_file="$5"
  [[ -z "$prefix" ]] && return

  cqlsh_exec -e "SELECT $select_columns, $id_column FROM ${CASSANDRA_KEYSPACE:-omnicare_dashboard}.$table;" \
    | awk -F'|' -v table="$table" -v id_column="$id_column" -v prefix="$prefix" '
        function trim(value) {
          gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
          return value
        }
        function quote(value) {
          gsub(/\047/, "\047\047", value)
          return "\047" value "\047"
        }
        function emit(delete_keys) {
          printf "DELETE FROM %s.%s WHERE %s;\n", keyspace, table, delete_keys
        }
        BEGIN {
          keyspace = ENVIRON["CASSANDRA_KEYSPACE"]
          if (keyspace == "") keyspace = "omnicare_dashboard"
        }
        table == "fact_order_line_by_day" {
          order_day = trim($1); fact_id = trim($2); id_value = trim($3)
          if (index(id_value, prefix) == 1) emit("order_day = " quote(order_day) " AND fact_id = " quote(fact_id))
        }
        table == "fact_payment_by_day" {
          payment_day = trim($1); fact_id = trim($2); id_value = trim($3)
          if (index(id_value, prefix) == 1) emit("payment_day = " quote(payment_day) " AND fact_id = " quote(fact_id))
        }
        table == "fact_refund_by_day" {
          refund_day = trim($1); fact_id = trim($2); id_value = trim($3)
          if (index(id_value, prefix) == 1) emit("refund_day = " quote(refund_day) " AND fact_id = " quote(fact_id))
        }
        table == "fact_inventory_movement_by_product" {
          product_id = trim($1); movement_ts = trim($2); fact_id = trim($3); id_value = trim($4)
          if (index(id_value, prefix) == 1) emit("product_id = " quote(product_id) " AND movement_ts = " quote(movement_ts) " AND fact_id = " quote(fact_id))
        }
        table == "fact_support_case_by_customer" {
          customer_id = trim($1); opened_day = trim($2); fact_id = trim($3); id_value = trim($4)
          if (index(id_value, prefix) == 1) emit("customer_id = " quote(customer_id) " AND opened_day = " quote(opened_day) " AND fact_id = " quote(fact_id))
        }
      ' >> "$output_file"
}

collect_source_position_deletes() {
  local position="$1"
  local output_file="$2"
  local escaped_position
  escaped_position="$(cql_escape "$position")"

  cqlsh_exec -e "SELECT order_day, fact_id FROM ${CASSANDRA_KEYSPACE:-omnicare_dashboard}.fact_order_line_by_day WHERE source_position = '$escaped_position' ALLOW FILTERING;" \
    | awk -F'|' 'function trim(v){gsub(/^[[:space:]]+|[[:space:]]+$/, "", v); return v} /^[[:space:]]*[0-9]{4}-[0-9]{2}-[0-9]{2}[[:space:]]*\|/ {printf "DELETE FROM %s.fact_order_line_by_day WHERE order_day = '\''%s'\'' AND fact_id = '\''%s'\'';\n", ENVIRON["CASSANDRA_KEYSPACE"] ? ENVIRON["CASSANDRA_KEYSPACE"] : "omnicare_dashboard", trim($1), trim($2)}' >> "$output_file"

  cqlsh_exec -e "SELECT payment_day, fact_id FROM ${CASSANDRA_KEYSPACE:-omnicare_dashboard}.fact_payment_by_day WHERE source_position = '$escaped_position' ALLOW FILTERING;" \
    | awk -F'|' 'function trim(v){gsub(/^[[:space:]]+|[[:space:]]+$/, "", v); return v} /^[[:space:]]*[0-9]{4}-[0-9]{2}-[0-9]{2}[[:space:]]*\|/ {printf "DELETE FROM %s.fact_payment_by_day WHERE payment_day = '\''%s'\'' AND fact_id = '\''%s'\'';\n", ENVIRON["CASSANDRA_KEYSPACE"] ? ENVIRON["CASSANDRA_KEYSPACE"] : "omnicare_dashboard", trim($1), trim($2)}' >> "$output_file"

  cqlsh_exec -e "SELECT refund_day, fact_id FROM ${CASSANDRA_KEYSPACE:-omnicare_dashboard}.fact_refund_by_day WHERE source_position = '$escaped_position' ALLOW FILTERING;" \
    | awk -F'|' 'function trim(v){gsub(/^[[:space:]]+|[[:space:]]+$/, "", v); return v} /^[[:space:]]*[0-9]{4}-[0-9]{2}-[0-9]{2}[[:space:]]*\|/ {printf "DELETE FROM %s.fact_refund_by_day WHERE refund_day = '\''%s'\'' AND fact_id = '\''%s'\'';\n", ENVIRON["CASSANDRA_KEYSPACE"] ? ENVIRON["CASSANDRA_KEYSPACE"] : "omnicare_dashboard", trim($1), trim($2)}' >> "$output_file"

  cqlsh_exec -e "SELECT product_id, movement_ts, fact_id FROM ${CASSANDRA_KEYSPACE:-omnicare_dashboard}.fact_inventory_movement_by_product WHERE source_position = '$escaped_position' ALLOW FILTERING;" \
    | awk -F'|' 'function trim(v){gsub(/^[[:space:]]+|[[:space:]]+$/, "", v); return v} {product_id=trim($1); movement_ts=trim($2); fact_id=trim($3)} product_id != "" && product_id != "product_id" && product_id !~ /^-+$/ && movement_ts != "movement_ts" && fact_id != "fact_id" {printf "DELETE FROM %s.fact_inventory_movement_by_product WHERE product_id = '\''%s'\'' AND movement_ts = '\''%s'\'' AND fact_id = '\''%s'\'';\n", ENVIRON["CASSANDRA_KEYSPACE"] ? ENVIRON["CASSANDRA_KEYSPACE"] : "omnicare_dashboard", product_id, movement_ts, fact_id}' >> "$output_file"

  cqlsh_exec -e "SELECT customer_id, opened_day, fact_id FROM ${CASSANDRA_KEYSPACE:-omnicare_dashboard}.fact_support_case_by_customer WHERE source_position = '$escaped_position' ALLOW FILTERING;" \
    | awk -F'|' 'function trim(v){gsub(/^[[:space:]]+|[[:space:]]+$/, "", v); return v} {customer_id=trim($1); opened_day=trim($2); fact_id=trim($3)} customer_id != "" && customer_id != "customer_id" && customer_id !~ /^-+$/ && opened_day != "opened_day" && fact_id != "fact_id" {printf "DELETE FROM %s.fact_support_case_by_customer WHERE customer_id = '\''%s'\'' AND opened_day = '\''%s'\'' AND fact_id = '\''%s'\'';\n", ENVIRON["CASSANDRA_KEYSPACE"] ? ENVIRON["CASSANDRA_KEYSPACE"] : "omnicare_dashboard", customer_id, opened_day, fact_id}' >> "$output_file"
}

collect_matching_deletes() {
  local output_file="$1"
  : > "$output_file"
  collect_prefix_deletes "fact_order_line_by_day" "order_item_id" "$order_item_id_prefix" "order_day, fact_id" "$output_file"
  collect_prefix_deletes "fact_payment_by_day" "payment_id" "$payment_id_prefix" "payment_day, fact_id" "$output_file"
  collect_prefix_deletes "fact_refund_by_day" "refund_id" "$refund_id_prefix" "refund_day, fact_id" "$output_file"
  collect_prefix_deletes "fact_inventory_movement_by_product" "movement_id" "$movement_id_prefix" "product_id, movement_ts, fact_id" "$output_file"
  collect_prefix_deletes "fact_support_case_by_customer" "ticket_id" "$ticket_id_prefix" "customer_id, opened_day, fact_id" "$output_file"
  if ((${#source_positions[@]} > 0)); then
    for position in "${source_positions[@]}"; do
      collect_source_position_deletes "$position" "$output_file"
    done
  fi
  sort -u "$output_file" -o "$output_file"
}

line_count() {
  awk 'NF {count++} END {print count + 0}' "$1"
}

capture_dashboard() {
  local label="$1"
  local snapshot_file="$2"
  local status_file="$3"

  if [[ "$skip_dashboard" == true ]]; then
    printf 'skipped\n' > "$status_file"
    return
  fi
  if ! curl -fsS "${dashboard_url%/}/api/dashboard" -o "$snapshot_file" >/dev/null 2>&1; then
    printf 'unavailable\n' > "$status_file"
    return
  fi
  python - "$snapshot_file" > "$status_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
quality = payload.get("dataQuality") or {}
print(quality.get("overallStatus") or "unknown")
PY
  log "$label dashboard quality: $(cat "$status_file")"
}

write_report() {
  local before_count="$1"
  local after_count="$2"
  local before_quality="$3"
  local after_quality="$4"
  local quality_gate_status="$5"
  local deletes_file="$6"
  local report_dir
  local source_positions_joined=""
  if ((${#source_positions[@]} > 0)); then
    source_positions_joined="${source_positions[*]}"
  fi
  report_dir="$(dirname "$report_file")"
  mkdir -p "$report_dir"
  python - "$report_file" "$before_count" "$after_count" "$before_quality" "$after_quality" "$quality_gate_status" "$deletes_file" \
    "$payment_id_prefix" "$refund_id_prefix" "$ticket_id_prefix" "$order_item_id_prefix" "$movement_id_prefix" "$source_positions_joined" <<'PY'
import json
import sys
import time

(
    report_path,
    before_count,
    after_count,
    before_quality,
    after_quality,
    quality_gate_status,
    deletes_path,
    payment_prefix,
    refund_prefix,
    ticket_prefix,
    order_item_prefix,
    movement_prefix,
    source_positions,
) = sys.argv[1:14]

with open(deletes_path, encoding="utf-8") as handle:
    delete_statements = [line.strip() for line in handle if line.strip()]

report = {
    "generatedAt": int(time.time()),
    "status": "passed" if int(after_count) == 0 and quality_gate_status in {"passed", "skipped"} else "failed",
    "scope": {
        "paymentIdPrefix": payment_prefix or None,
        "refundIdPrefix": refund_prefix or None,
        "ticketIdPrefix": ticket_prefix or None,
        "orderItemIdPrefix": order_item_prefix or None,
        "movementIdPrefix": movement_prefix or None,
        "sourcePositions": source_positions.split() if source_positions else [],
    },
    "checks": {
        "matchingRowsBefore": int(before_count),
        "matchingRowsAfter": int(after_count),
        "deletedRows": max(0, int(before_count) - int(after_count)),
        "dashboardQualityBefore": before_quality,
        "dashboardQualityAfter": after_quality,
        "qualityGateAfter": quality_gate_status,
    },
    "deleteStatementCount": len(delete_statements),
}

with open(report_path, "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
}

require_scope
validate_prefix "--payment-id-prefix" "$payment_id_prefix"
validate_prefix "--refund-id-prefix" "$refund_id_prefix"
validate_prefix "--ticket-id-prefix" "$ticket_id_prefix"
validate_prefix "--order-item-id-prefix" "$order_item_id_prefix"
validate_prefix "--movement-id-prefix" "$movement_id_prefix"

if ! positive_integer "$max_snapshot_age_seconds"; then
  echo "--max-snapshot-age-seconds must be a positive integer." >&2
  exit 2
fi

if [[ "$dry_run" == true ]]; then
  log "dry-run recovery plan"
  printf '+ scope payment_id_prefix=%q refund_id_prefix=%q ticket_id_prefix=%q order_item_id_prefix=%q movement_id_prefix=%q\n' \
    "$payment_id_prefix" "$refund_id_prefix" "$ticket_id_prefix" "$order_item_id_prefix" "$movement_id_prefix"
  if ((${#source_positions[@]} > 0)); then
    for position in "${source_positions[@]}"; do
      printf '+ source_position=%q\n' "$position"
    done
  fi
  printf '+ would collect matching Cassandra primary keys, delete only those rows, capture dashboard quality, and write %q\n' "$report_file"
  exit 0
fi

if [[ "$confirm" != true ]]; then
  echo "Live recovery deletes require --yes." >&2
  exit 2
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
before_deletes="$work_dir/before-deletes.cql"
after_deletes="$work_dir/after-deletes.cql"
before_snapshot="$work_dir/dashboard-before.json"
after_snapshot="$work_dir/dashboard-after.json"
before_quality_file="$work_dir/before-quality.txt"
after_quality_file="$work_dir/after-quality.txt"

capture_dashboard "before" "$before_snapshot" "$before_quality_file"
collect_matching_deletes "$before_deletes"
before_count="$(line_count "$before_deletes")"
log "matching rows before cleanup: $before_count"

if (( before_count > 0 )); then
  cqlsh_exec < "$before_deletes"
fi

collect_matching_deletes "$after_deletes"
after_count="$(line_count "$after_deletes")"
log "matching rows after cleanup: $after_count"

capture_dashboard "after" "$after_snapshot" "$after_quality_file"
quality_gate_status="skipped"
if [[ "$skip_dashboard" != true && ! -s "$after_snapshot" ]]; then
  quality_gate_status="unavailable"
elif [[ "$skip_dashboard" != true ]]; then
  if python tools/quality_gate.py \
    --snapshot-file "$after_snapshot" \
    --max-snapshot-age-seconds "$max_snapshot_age_seconds" >/dev/null 2>&1; then
    quality_gate_status="passed"
  else
    quality_gate_status="failed"
  fi
fi

write_report \
  "$before_count" \
  "$after_count" \
  "$(cat "$before_quality_file")" \
  "$(cat "$after_quality_file")" \
  "$quality_gate_status" \
  "$before_deletes"

log "recovery report: $report_file"
if (( after_count > 0 )); then
  echo "Recovery left matching rows in Cassandra: $after_count." >&2
  exit 1
fi
if [[ "$quality_gate_status" == "failed" ]]; then
  echo "Dashboard quality gate still fails after cleanup." >&2
  exit 1
fi
if [[ "$quality_gate_status" == "unavailable" ]]; then
  echo "Dashboard quality gate was unavailable after cleanup." >&2
  exit 1
fi
log "recovery cleanup completed"
