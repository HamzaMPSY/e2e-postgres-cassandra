# Production Connector Templates

CDCV2-016 keeps local demo connector files separate from production templates:

- `connectors/*.json`: local Compose connectors rendered by `scripts/register-connectors.sh`.
- `connectors/production/*.json`: production-ready templates that assume Kafka Connect config providers, TLS, and explicit redacted logging defaults.

The production templates are not meant to be registered with `envsubst`. They should be applied by the target platform after the Kafka Connect worker has a secret provider installed.

## Required Worker Capabilities

Every production Kafka Connect worker must support:

- A `secrets` config provider.
- Connector client overrides through `connector.client.config.override.policy=All`.
- TLS material mounted as files when the connector or Kafka client expects file paths.
- Log configuration that keeps connector error payloads out of logs.

AWS MSK Connect example:

```properties
config.providers=secrets
config.providers.secrets.class=com.github.jcustenborder.kafka.config.aws.SecretsManagerConfigProvider
connector.client.config.override.policy=All
errors.log.include.messages=false
```

Strimzi example:

```yaml
config:
  config.providers: secrets
  config.providers.secrets.class: io.strimzi.kafka.KubernetesSecretConfigProvider
  connector.client.config.override.policy: All
  errors.log.include.messages: false
```

## Template Contract

Each template must include:

| Control | Requirement |
| --- | --- |
| Config providers | Source credentials, Kafka TLS material, and database TLS material use `${secrets:...}` references. |
| Source TLS | PostgreSQL uses `database.sslmode=verify-full`; MySQL uses `database.ssl.mode=verify_identity`; MongoDB enables `tls=true`; Oracle references a wallet file. |
| Kafka TLS | Connector producers and Debezium signal clients use `SSL` or `SASL_SSL`. |
| Logging | `errors.log.include.messages=false`, `errors.log.enable=true`, and `errors.tolerance=none`. |
| Signaling | Source and Kafka signaling stay enabled for production resnapshot runbooks. |

## Validation

Run:

```bash
python tools/validate_config.py
python tools/security_check.py
python tools/validate_deployments.py
```

`tools/validate_config.py` validates production templates recursively under `connectors/production/`. It rejects missing config provider references, missing Kafka TLS producer/signal settings, incomplete source TLS settings, and unsafe connector logging defaults.

## Promotion Flow

1. Create platform secrets under the paths referenced by the template.
2. Mount any truststores, keystores, CA bundles, or Oracle wallets into Kafka Connect workers.
3. Confirm the worker config provider resolves the `${secrets:...}` references.
4. Register one connector in a non-production environment and verify it captures an initial snapshot.
5. Register production connectors with change approval and monitor Debezium lag, task state, Kafka lag, and DLQ volume.
