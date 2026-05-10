# AWS Deployment Skeleton

Use this path when Kafka is strategic and the CDC contract should remain Kafka-compatible across sources and consumers.

```mermaid
flowchart LR
  DB["RDS / Aurora / EC2 databases"] --> CONNECT["MSK Connect + Debezium plugins"]
  SM["Secrets Manager"] --> CONNECT
  CONNECT --> MSK["Amazon MSK"]
  MSK --> TRANSFORMER["ECS task or EKS deployment"]
  TRANSFORMER --> CASS["Cassandra / Amazon Keyspaces / Astra"]
  CASS --> TRINO["Trino"]
  TRINO --> DASH["Dashboard / BI"]
  CW["CloudWatch"] <-.-> CONNECT
  CW <-.-> TRANSFORMER
```

## Files

- `main.tf`: infrastructure skeleton for MSK Connect workers, connector placeholders, replay job log groups, and runtime IAM boundaries.
- `worker.properties`: MSK Connect worker defaults for secret config providers, connector client overrides, and safe connector logging.
- `variables.tf`: required environment inputs.
- `outputs.tf`: integration values for downstream deployment stages.

## Production Decisions

- Source credentials and TLS material come from Secrets Manager.
- MSK Connect uses TLS in transit.
- Connector configs are supplied through `var.connectors`; start from `config/connectors/production/` and resolve `${secrets:...}` values through the configured worker provider.
- Transformer can run as ECS, EKS, or AWS Batch. This skeleton exposes the inputs those runtimes need without choosing one prematurely.
