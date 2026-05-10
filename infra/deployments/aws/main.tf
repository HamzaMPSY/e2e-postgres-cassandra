terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  security_controls = jsondecode(file("${path.module}/../../docs/v2/security-controls.json"))
  common_tags = merge(
    var.tags,
    {
      system = "omnicare-cdc"
      ticket = "CDCV2-012"
    }
  )
}

resource "aws_cloudwatch_log_group" "msk_connect" {
  name              = "/omnicare-cdc/${var.environment}/msk-connect"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "transformer" {
  name              = "/omnicare-cdc/${var.environment}/transformer"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = local.common_tags
}

resource "aws_mskconnect_worker_configuration" "debezium" {
  name                    = "omnicare-${var.environment}-debezium-worker"
  description             = "Worker settings for OmniCare CDC Debezium connectors."
  properties_file_content = file("${path.module}/worker.properties")
}

resource "aws_mskconnect_connector" "source" {
  for_each = var.connectors

  name                 = "omnicare-${var.environment}-${each.key}"
  kafkaconnect_version = var.kafka_connect_version

  capacity {
    autoscaling {
      mcu_count        = each.value.mcu_count
      min_worker_count = each.value.min_workers
      max_worker_count = each.value.max_workers

      scale_in_policy {
        cpu_utilization_percentage = 25
      }

      scale_out_policy {
        cpu_utilization_percentage = 75
      }
    }
  }

  connector_configuration = each.value.connector_configuration

  kafka_cluster {
    apache_kafka_cluster {
      bootstrap_servers = var.msk_bootstrap_brokers_tls

      vpc {
        security_groups = var.connector_security_group_ids
        subnets         = var.private_subnet_ids
      }
    }
  }

  kafka_cluster_client_authentication {
    authentication_type = var.kafka_client_authentication_type
  }

  kafka_cluster_encryption_in_transit {
    encryption_type = "TLS"
  }

  plugin {
    custom_plugin {
      arn      = var.debezium_plugin_arn
      revision = var.debezium_plugin_revision
    }
  }

  service_execution_role_arn = var.msk_connect_execution_role_arn

  worker_configuration {
    arn      = aws_mskconnect_worker_configuration.debezium.arn
    revision = aws_mskconnect_worker_configuration.debezium.latest_revision
  }

  log_delivery {
    worker_log_delivery {
      cloudwatch_logs {
        enabled   = true
        log_group = aws_cloudwatch_log_group.msk_connect.name
      }
    }
  }

  tags = local.common_tags
}

resource "aws_iam_policy" "transformer_runtime" {
  name        = "omnicare-${var.environment}-transformer-runtime"
  description = "Minimum runtime access for transformer and replay jobs."
  policy      = data.aws_iam_policy_document.transformer_runtime.json
  tags        = local.common_tags
}

data "aws_iam_policy_document" "transformer_runtime" {
  statement {
    sid = "ReadRuntimeSecrets"
    actions = [
      "secretsmanager:GetSecretValue"
    ]
    resources = var.transformer_secret_arns
  }

  statement {
    sid = "WriteLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "${aws_cloudwatch_log_group.transformer.arn}:*"
    ]
  }
}
