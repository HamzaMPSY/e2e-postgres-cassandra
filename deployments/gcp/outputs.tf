output "datastream_stream_ids" {
  description = "Datastream stream IDs keyed by source."
  value       = { for name, stream in google_datastream_stream.source : name => stream.id }
}

output "dataflow_service_account_email" {
  description = "Service account used by the CDC Dataflow job."
  value       = google_service_account.dataflow.email
}

output "cdc_landing_bucket" {
  description = "GCS landing bucket for CDC events."
  value       = google_storage_bucket.cdc_landing.name
}

output "runtime_secret_ids" {
  description = "Secret Manager secret IDs managed by this skeleton."
  value       = keys(google_secret_manager_secret.runtime)
}
