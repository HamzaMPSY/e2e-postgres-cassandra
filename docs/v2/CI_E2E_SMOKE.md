# CI E2E Smoke Profiles

The E2E validation is split into two profiles so pull-request CI stays fast while the project still has a production-like live path.

The CI dry-run profile also runs:

```bash
scripts/local-preflight.sh --dry-run --env-file .env.example --skip-podman
scripts/local-status.sh --dry-run --skip-podman
```

That confirms the local preflight and operator status command paths without requiring Podman on generic hosted runners.

## Pull Request Smoke

GitHub Actions runs the `e2e-smoke` job on every push and pull request:

```bash
scripts/demo-e2e.sh \
  --dry-run \
  --env-file .env.example \
  --max-events 2 \
  --rate-per-second 1 \
  --transformer-max-messages 10 \
  --timeout-seconds 30
```

This profile does not start containers. It proves that the operator entrypoint, env-file handling, connector registration command, generator command, transformer command, Cassandra verification step, dashboard verification step, and report path remain wired.

Use it to catch broken script arguments, renamed paths, missing local contracts, and accidental removal of the demo harness from CI.

## Manual Live Smoke

The `e2e-live` job is available through `workflow_dispatch` only. Set `run-live-e2e=true` and provide a runner label that points to a prepared Linux runner.

The runner must have:

- Podman with Compose support.
- Python 3.11.
- `curl`.
- `jq`.
- `envsubst`.
- Enough CPU and memory for Kafka, Kafka Connect, Cassandra, Trino, PostgreSQL, MySQL, MongoDB, the dashboard, and observability services.

The live job runs:

```bash
cp .env.example .env
python -m pip install -e generator
scripts/demo-e2e.sh \
  --env-file .env \
  --max-events 10 \
  --rate-per-second 2 \
  --transformer-max-messages 200 \
  --timeout-seconds 300
```

It uploads `artifacts/demo-report.json` when the report exists.

## Production Gate Recommendation

Use the pull-request dry run as a required check for normal code review. Run the live smoke on a scheduled self-hosted runner, before demo branches, and before changes to connector templates, source schemas, transformer mapping logic, Cassandra serving tables, or dashboard queries.

Do not run the live Podman stack on generic hosted CI unless the job has been explicitly sized and isolated. CDC integration tests are stateful and resource-heavy; they should run on runners where disk, memory, and container cleanup are operationally owned.
