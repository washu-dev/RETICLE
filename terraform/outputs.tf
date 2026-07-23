output "role_arn" {
  description = "ARN of the IAM role that can read the secrets. Assume this role to fetch them."
  value       = aws_iam_role.secrets_reader.arn
}

output "kms_key_arn" {
  description = "ARN of the customer-managed KMS key encrypting the secrets."
  value       = aws_kms_key.secrets.arn
}

output "secret_arns" {
  description = "Map of secret name => ARN for every managed secret."
  value       = { for k, s in aws_secretsmanager_secret.this : s.name => s.arn }
}

output "sso_ci_reader_role_arn" {
  description = "ARN of the SSO-only CI reader role (null if not created). Set this as RETICLE_SSO_CI_ROLE_ARN in the webapp workflow."
  value       = local.create_ci_role ? aws_iam_role.sso_ci_reader[0].arn : null
}
