#!/usr/bin/env bash
set -euo pipefail

CONNECT_URL="${CONNECT_URL:-http://localhost:18083}"
ENV_FILE="${ENV_FILE:-.env}"

if ! command -v envsubst >/dev/null 2>&1; then
  echo "envsubst is required to render local connector templates." >&2
  echo "Install gettext, or configure Kafka Connect config providers for production." >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing env file: $ENV_FILE" >&2
  echo "Create it from .env.example first." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

for connector in config/connectors/postgres-orders.json config/connectors/mysql-billing.json config/connectors/mongo-engagement.json; do
  echo "Registering $(basename "$connector")"
  rendered="$(mktemp)"
  config="$(mktemp)"
  envsubst < "$connector" > "$rendered"
  name="$(jq -r '.name' "$rendered")"
  jq -c '.config' "$rendered" > "$config"

  if curl -fsS "$CONNECT_URL/connectors/$name" >/dev/null 2>&1; then
    curl -fsS -X PUT "$CONNECT_URL/connectors/$name/config" \
      -H "Accept: application/json" \
      -H "Content-Type: application/json" \
      --data @"$config"
  else
    curl -fsS -X POST "$CONNECT_URL/connectors" \
      -H "Accept: application/json" \
      -H "Content-Type: application/json" \
      --data @"$rendered"
  fi

  rm -f "$rendered" "$config"
  echo
done

echo "Connector registration complete."
