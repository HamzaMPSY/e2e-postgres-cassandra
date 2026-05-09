#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/request-resnapshot.sh --connector CONNECTOR --data-collection NAME [options]

Requests a Debezium incremental snapshot through the Kafka signal channel.

Examples:
  scripts/request-resnapshot.sh --connector postgres-orders-local --data-collection public.customers
  scripts/request-resnapshot.sh --connector mysql-billing-local --data-collection billing.payments
  scripts/request-resnapshot.sh --connector mongo-engagement-local --data-collection engagement.support_tickets

Options:
  --connector NAME              Connector name.
  --data-collection NAME        Table/collection to resnapshot. Can be repeated.
  --signal-key KEY              Override signal key. Defaults from connector.
  --signal-topic TOPIC          Default: DEBEZIUM_SIGNAL_TOPIC or cdc.local.omnicare.signals.
  --skip-topic-create           Do not create the local Kafka signal topic before producing.
  --dry-run                     Print signal payload and producer command only.
  -h, --help                    Show help.
USAGE
}

connector=""
signal_key=""
signal_topic="${DEBEZIUM_SIGNAL_TOPIC:-cdc.local.omnicare.signals}"
collections=()
dry_run=false
create_topic=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --connector)
      connector="${2:?Missing value for --connector}"
      shift 2
      ;;
    --data-collection)
      collections+=("${2:?Missing value for --data-collection}")
      shift 2
      ;;
    --signal-key)
      signal_key="${2:?Missing value for --signal-key}"
      shift 2
      ;;
    --signal-topic)
      signal_topic="${2:?Missing value for --signal-topic}"
      shift 2
      ;;
    --skip-topic-create)
      create_topic=false
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

if [[ -z "$connector" ]]; then
  echo "Missing --connector." >&2
  exit 2
fi
if [[ ${#collections[@]} -eq 0 ]]; then
  echo "At least one --data-collection is required." >&2
  exit 2
fi

if [[ -z "$signal_key" ]]; then
  case "$connector" in
    postgres-orders-local) signal_key="cdc.local.omnicare.postgres" ;;
    mysql-billing-local) signal_key="cdc.local.omnicare.mysql" ;;
    mongo-engagement-local) signal_key="cdc.local.omnicare.mongo" ;;
    oracle-erp-local) signal_key="cdc.local.omnicare.oracle" ;;
    *)
      echo "Unknown connector '$connector'. Pass --signal-key explicitly." >&2
      exit 2
      ;;
  esac
fi

payload="$(
  python3 -c 'import json, sys; print(json.dumps({"type": "execute-snapshot", "data": {"type": "INCREMENTAL", "data-collections": sys.argv[1:]}}))' \
    "${collections[@]}"
)"

echo "Connector: $connector"
echo "Signal topic: $signal_topic"
echo "Signal key: $signal_key"
echo "Payload: $payload"

producer=(
  podman exec -i omnicare-kafka
  kafka-console-producer
  --bootstrap-server kafka:9092
  --topic "$signal_topic"
  --property parse.key=true
  --property key.separator=$'\t'
)

if [[ "$dry_run" == true ]]; then
  if [[ "$create_topic" == true ]]; then
    printf '%q ' \
      podman exec omnicare-kafka kafka-topics \
      --bootstrap-server kafka:9092 \
      --create \
      --if-not-exists \
      --topic "$signal_topic" \
      --partitions 1 \
      --replication-factor 1 \
      --config cleanup.policy=delete
    printf '\n'
  fi
  printf '%s\t%s\n' "$signal_key" "$payload"
  printf '%q ' "${producer[@]}"
  printf '\n'
  exit 0
fi

if [[ "$create_topic" == true ]]; then
  podman exec omnicare-kafka kafka-topics \
    --bootstrap-server kafka:9092 \
    --create \
    --if-not-exists \
    --topic "$signal_topic" \
    --partitions 1 \
    --replication-factor 1 \
    --config cleanup.policy=delete >/dev/null
fi

printf '%s\t%s\n' "$signal_key" "$payload" | "${producer[@]}"
echo "Resnapshot signal submitted."
