#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/connect-connector.sh ACTION CONNECTOR [options]

Actions:
  status    Show connector status.
  config    Show connector config.
  offsets   Show connector offsets.
  pause     Pause connector.
  resume    Resume connector.
  stop      Stop connector. Required before offset reset in supported Connect versions.
  restart   Restart connector and include tasks.
  reset-offsets
            Delete connector offsets. Requires --yes and a stopped connector.
  delete    Delete connector. Requires --yes.

Options:
  --connect-url URL   Default: http://localhost:18083
  --yes               Required for delete and reset-offsets.
  -h, --help          Show help.
USAGE
}

connect_url="${CONNECT_URL:-http://localhost:18083}"
yes=false

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

action="$1"
shift

if [[ "$action" == "-h" || "$action" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 1 ]]; then
  echo "Missing connector name." >&2
  usage >&2
  exit 2
fi

connector="$1"
shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --connect-url)
      connect_url="${2:?Missing value for --connect-url}"
      shift 2
      ;;
    --yes)
      yes=true
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

case "$action" in
  status)
    curl -fsS "$connect_url/connectors/$connector/status"
    echo
    ;;
  config)
    curl -fsS "$connect_url/connectors/$connector/config"
    echo
    ;;
  offsets)
    curl -fsS "$connect_url/connectors/$connector/offsets"
    echo
    ;;
  pause)
    curl -fsS -X PUT "$connect_url/connectors/$connector/pause" >/dev/null
    echo "Paused $connector"
    ;;
  resume)
    curl -fsS -X PUT "$connect_url/connectors/$connector/resume" >/dev/null
    echo "Resumed $connector"
    ;;
  stop)
    curl -fsS -X PUT "$connect_url/connectors/$connector/stop" >/dev/null
    echo "Stopped $connector"
    ;;
  restart)
    curl -fsS -X POST "$connect_url/connectors/$connector/restart?includeTasks=true&onlyFailed=false" >/dev/null
    echo "Restarted $connector"
    ;;
  reset-offsets)
    if [[ "$yes" != true ]]; then
      echo "Refusing to reset offsets for $connector without --yes." >&2
      exit 2
    fi
    curl -fsS -X DELETE "$connect_url/connectors/$connector/offsets" >/dev/null
    echo "Reset offsets for $connector"
    ;;
  delete)
    if [[ "$yes" != true ]]; then
      echo "Refusing to delete $connector without --yes." >&2
      exit 2
    fi
    curl -fsS -X DELETE "$connect_url/connectors/$connector" >/dev/null
    echo "Deleted $connector"
    ;;
  *)
    echo "Unknown action: $action" >&2
    usage >&2
    exit 2
    ;;
esac
