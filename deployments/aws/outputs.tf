output "msk_connect_connector_arns" {
  description = "MSK Connect connector ARNs keyed by connector name."
  value       = { for name, connector in aws_mskconnect_connector.source : name => connector.arn }
}

output "transformer_runtime_policy_arn" {
  description = "IAM policy ARN for transformer and replay job runtime access."
  value       = aws_iam_policy.transformer_runtime.arn
}

output "security_control_connectors" {
  description = "Connector names covered by the security control catalog."
  value       = keys(local.security_controls.connectors)
}
