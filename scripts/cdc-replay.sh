#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/cdc-replay.sh --topic TOPIC [options]
  scripts/cdc-replay.sh --all-active [options]

Replays Kafka CDC records into Cassandra with a fresh transformer consumer group.

Options:
  --topic TOPIC                 Replay one CDC topic. Can be repeated.
  --all-active                  Replay active local topics.
  --group-id GROUP              Consumer group to use. Defaults to replay timestamp.
  --max-messages N              Max Kafka messages to process. Default: 1000.
  --idle-timeout-seconds N      Stop after this idle period. Default: 15.
  --env-file FILE               Optional env file. Default: .env if present.
  --dry-run                     Print resolved command without running it.
  -h, --help                    Show help.

Host defaults intentionally use localhost ports:
  REPLAY_KAFKA_BOOTSTRAP_SERVERS=localhost:19092
  REPLAY_CASSANDRA_CONTACT_POINTS=127.0.0.1
USAGE
}

topics=()
all_active=false
group_id="replay-$(date -u +%Y%m%dT%H%M%SZ)"
max_messages=1000
idle_timeout_seconds=15
env_file=".env"
dry_run=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --topic)
      topics+=("${2:?Missing value for --topic}")
      shift 2
      ;;
    --all-active)
      all_active=true
      shift
      ;;
    --group-id)
      group_id="${2:?Missing value for --group-id}"
      shift 2
      ;;
    --max-messages)
      max_messages="${2:?Missing value for --max-messages}"
      shift 2
      ;;
    --idle-timeout-seconds)
      idle_timeout_seconds="${2:?Missing value for --idle-timeout-seconds}"
      shift 2
      ;;
    --env-file)
      env_file="${2:?Missing value for --env-file}"
      shift 2
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

if [[ "$all_active" == true && ${#topics[@]} -gt 0 ]]; then
  echo "Use either --all-active or --topic, not both." >&2
  exit 2
fi

if [[ "$all_active" == false && ${#topics[@]} -eq 0 ]]; then
  echo "Missing replay scope: pass --topic or --all-active." >&2
  usage >&2
  exit 2
fi

if ! [[ "$max_messages" =~ ^[1-9][0-9]*$ ]]; then
  echo "--max-messages must be a positive integer." >&2
  exit 2
fi

if [[ -f "$env_file" ]]; then
  set -a
  source "$env_file"
  set +a
elif [[ "$env_file" != ".env" ]]; then
  echo "Missing env file: $env_file" >&2
  exit 2
fi

if [[ "$all_active" == true ]]; then
  topics=(
    "cdc.local.omnicare.postgres.public.customers"
    "cdc.local.omnicare.postgres.public.order_items"
    "cdc.local.omnicare.postgres.public.products"
    "cdc.local.omnicare.postgres.public.stock_movements"
    "cdc.local.omnicare.mysql.billing.payments"
    "cdc.local.omnicare.mysql.billing.refunds"
    "cdc.local.omnicare.mongo.engagement.support_tickets"
  )
fi

export KAFKA_BOOTSTRAP_SERVERS="${REPLAY_KAFKA_BOOTSTRAP_SERVERS:-localhost:19092}"
export KAFKA_GROUP_ID="$group_id"
export CDC_SOURCE_TOPICS="$(IFS=,; echo "${topics[*]}")"
export DLQ_TOPIC="${DLQ_TOPIC:-dlq.local.omnicare.transformer}"
export CASSANDRA_CONTACT_POINTS="${REPLAY_CASSANDRA_CONTACT_POINTS:-127.0.0.1}"
export CASSANDRA_KEYSPACE="${CASSANDRA_KEYSPACE:-omnicare_dashboard}"
export CASSANDRA_LOCAL_DC="${CASSANDRA_LOCAL_DC:-datacenter1}"
export CASSANDRA_PROTOCOL_VERSION="${CASSANDRA_PROTOCOL_VERSION:-5}"
export TRANSFORMER_METRICS_ENABLED="${TRANSFORMER_METRICS_ENABLED:-false}"

cmd=(
  python -m omnicare_cdc.main
  --max-messages "$max_messages"
  --idle-timeout-seconds "$idle_timeout_seconds"
)

echo "Replay consumer group: $KAFKA_GROUP_ID"
echo "Replay topics: $CDC_SOURCE_TOPICS"
echo "Kafka: $KAFKA_BOOTSTRAP_SERVERS"
echo "Cassandra: $CASSANDRA_CONTACT_POINTS / $CASSANDRA_KEYSPACE"

if [[ "$dry_run" == true ]]; then
  printf 'cd transformer && PYTHONPATH=src'
  printf ' %q=%q' \
    KAFKA_BOOTSTRAP_SERVERS "$KAFKA_BOOTSTRAP_SERVERS" \
    KAFKA_GROUP_ID "$KAFKA_GROUP_ID" \
    CDC_SOURCE_TOPICS "$CDC_SOURCE_TOPICS" \
    DLQ_TOPIC "$DLQ_TOPIC" \
    CASSANDRA_CONTACT_POINTS "$CASSANDRA_CONTACT_POINTS" \
    CASSANDRA_KEYSPACE "$CASSANDRA_KEYSPACE" \
    CASSANDRA_LOCAL_DC "$CASSANDRA_LOCAL_DC" \
    CASSANDRA_PROTOCOL_VERSION "$CASSANDRA_PROTOCOL_VERSION" \
    TRANSFORMER_METRICS_ENABLED "$TRANSFORMER_METRICS_ENABLED"
  printf ' %q' "${cmd[@]}"
  printf '\n'
  exit 0
fi

cd transformer
PYTHONPATH=src "${cmd[@]}"
