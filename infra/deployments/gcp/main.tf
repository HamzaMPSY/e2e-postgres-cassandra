terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

locals {
  security_controls = jsondecode(file("${path.module}/../../docs/v2/security-controls.json"))
  labels = merge(
    var.labels,
    {
      system = "omnicare-cdc"
      ticket = "cdcv2-012"
    }
  )
}

resource "google_service_account" "dataflow" {
  account_id   = "omnicare-${var.environment}-dataflow"
  display_name = "OmniCare CDC ${var.environment} Dataflow"
}

resource "google_secret_manager_secret" "runtime" {
  for_each  = var.runtime_secret_ids
  secret_id = each.value

  replication {
    auto {}
  }

  labels = local.labels
}

resource "google_storage_bucket" "cdc_landing" {
  name                        = var.cdc_landing_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  labels                      = local.labels
}

resource "google_datastream_private_connection" "source" {
  display_name          = "omnicare-${var.environment}-source-private-connection"
  location              = var.region
  private_connection_id = "omnicare-${var.environment}-source"

  vpc_peering_config {
    vpc    = var.vpc_self_link
    subnet = var.datastream_private_subnet_cidr
  }
}

resource "google_datastream_connection_profile" "source" {
  for_each              = var.connection_profiles
  display_name          = "omnicare-${var.environment}-${each.key}"
  location              = var.region
  connection_profile_id = "omnicare-${var.environment}-${each.key}"

  dynamic "postgresql_profile" {
    for_each = each.value.engine == "postgresql" ? [each.value] : []
    content {
      hostname = postgresql_profile.value.hostname
      port     = postgresql_profile.value.port
      username = postgresql_profile.value.username_secret_ref
      database = postgresql_profile.value.database
    }
  }

  dynamic "mysql_profile" {
    for_each = each.value.engine == "mysql" ? [each.value] : []
    content {
      hostname = mysql_profile.value.hostname
      port     = mysql_profile.value.port
      username = mysql_profile.value.username_secret_ref
    }
  }
}

resource "google_datastream_stream" "source" {
  for_each    = var.streams
  stream_id   = "omnicare-${var.environment}-${each.key}"
  location    = var.region
  display_name = "omnicare-${var.environment}-${each.key}"
  desired_state = "RUNNING"

  source_config {
    source_connection_profile = google_datastream_connection_profile.source[each.value.connection_profile_key].id
  }

  destination_config {
    destination_connection_profile = var.gcs_destination_connection_profile_id
    gcs_destination_config {
      path = "datastream/${each.key}"
    }
  }

  backfill_all {}
}

resource "google_dataflow_flex_template_job" "cdc_transform" {
  provider                = google-beta
  name                    = "omnicare-${var.environment}-cdc-transform"
  region                  = var.region
  container_spec_gcs_path = var.dataflow_flex_template_gcs_path
  service_account_email   = google_service_account.dataflow.email
  enable_streaming_engine = true
  network                 = var.vpc_name
  subnetwork              = var.dataflow_subnetwork
  ip_configuration        = "WORKER_IP_PRIVATE"
  labels                  = local.labels

  parameters = {
    inputPath              = "gs://${google_storage_bucket.cdc_landing.name}/datastream"
    securityControlsPath   = "docs/v2/security-controls.json"
    cassandraContactPoints = var.cassandra_contact_points
  }
}
