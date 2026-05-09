# Deployment Templates

These templates are production skeletons for CDCV2-012. They are not a one-command deployment; they define the environment-specific shape that a platform team can wire to real networks, images, certificates, and secret managers.

| Path | Environment | Main path |
| --- | --- | --- |
| `deployments/aws` | AWS | MSK, MSK Connect, ECS/EKS transformer jobs, Secrets Manager, CloudWatch |
| `deployments/gcp` | GCP | Datastream, Pub/Sub, Dataflow Flex Template, Secret Manager, GKE/Cloud Run option |
| `deployments/datacenter/helm/omnicare-cdc` | Datacenter Kubernetes | Strimzi Kafka/Kafka Connect, Vault/External Secrets, transformer deployment |

All deployment paths must honor:

- `docs/v2/security-controls.json` for secrets, TLS, ACL, PII, and source-user controls.
- `docs/v2/CONNECTOR_TEMPLATES.md` for production connector config provider, TLS, and logging requirements.
- `docs/v2/RUNBOOKS.md` for replay, resnapshot, and recovery operations.
- Immutable application images for `transformer`, `dashboard`, and `observability/exporter`.

## Promotion Flow

1. Build and scan container images.
2. Publish immutable image tags.
3. Apply environment infrastructure.
4. Register connector configs through a secret-aware deployment path.
5. Run `python tools/validate_deployments.py`, `python tools/security_check.py`, and `python tools/validate_config.py`.
6. Execute smoke replay with a short-lived replay group.
