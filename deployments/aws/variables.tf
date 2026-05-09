variable "region" {
  type        = string
  description = "AWS region."
}

variable "environment" {
  type        = string
  description = "Environment name such as dev, stage, or prod."
}

variable "kms_key_arn" {
  type        = string
  description = "KMS key ARN for logs and secret encryption."
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention period."
  default     = 30
}

variable "msk_bootstrap_brokers_tls" {
  type        = string
  description = "TLS bootstrap brokers for the MSK cluster."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnets used by MSK Connect workers."
}

variable "connector_security_group_ids" {
  type        = list(string)
  description = "Security groups attached to MSK Connect workers."
}

variable "kafka_client_authentication_type" {
  type        = string
  description = "MSK Connect client auth mode, for example NONE, IAM, or SASL_SCRAM."
  default     = "SASL_SCRAM"
}

variable "kafka_connect_version" {
  type        = string
  description = "Kafka Connect runtime version certified with the Debezium plugin."
  default     = "2.7.1"
}

variable "debezium_plugin_arn" {
  type        = string
  description = "MSK Connect custom plugin ARN containing certified Debezium connectors."
}

variable "debezium_plugin_revision" {
  type        = number
  description = "MSK Connect custom plugin revision."
}

variable "msk_connect_execution_role_arn" {
  type        = string
  description = "IAM role ARN used by MSK Connect workers."
}

variable "transformer_secret_arns" {
  type        = list(string)
  description = "Secrets Manager ARNs needed by transformer and replay jobs."
  default     = []
}

variable "connectors" {
  description = "Connector definitions supplied by environment-specific overlays."
  type = map(object({
    connector_configuration = map(string)
    mcu_count               = number
    min_workers             = number
    max_workers             = number
  }))
  default = {}
}

variable "tags" {
  type        = map(string)
  description = "Common resource tags."
  default     = {}
}
