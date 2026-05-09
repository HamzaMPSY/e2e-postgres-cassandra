variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "region" {
  type        = string
  description = "GCP region."
}

variable "environment" {
  type        = string
  description = "Environment name such as dev, stage, or prod."
}

variable "vpc_name" {
  type        = string
  description = "VPC name for Dataflow workers."
}

variable "vpc_self_link" {
  type        = string
  description = "VPC self link for Datastream private connectivity."
}

variable "datastream_private_subnet_cidr" {
  type        = string
  description = "CIDR reserved for Datastream private connectivity."
}

variable "dataflow_subnetwork" {
  type        = string
  description = "Subnetwork self link for private Dataflow workers."
}

variable "cdc_landing_bucket_name" {
  type        = string
  description = "GCS bucket used for Datastream CDC landing files."
}

variable "gcs_destination_connection_profile_id" {
  type        = string
  description = "Datastream GCS destination connection profile ID."
}

variable "dataflow_flex_template_gcs_path" {
  type        = string
  description = "GCS path to the Dataflow Flex Template spec."
}

variable "runtime_secret_ids" {
  type        = set(string)
  description = "Secret Manager secret IDs required by Datastream/Dataflow runtime."
  default     = []
}

variable "cassandra_contact_points" {
  type        = string
  description = "Comma-separated Cassandra contact points passed to the transform job."
}

variable "connection_profiles" {
  description = "Source connection profile skeletons. Secret refs must resolve at deploy time."
  type = map(object({
    engine              = string
    hostname            = string
    port                = number
    username_secret_ref = string
    database            = optional(string)
  }))
  default = {}
}

variable "streams" {
  description = "Datastream streams keyed by source name."
  type = map(object({
    connection_profile_key = string
  }))
  default = {}
}

variable "labels" {
  type        = map(string)
  description = "Common GCP labels."
  default     = {}
}
