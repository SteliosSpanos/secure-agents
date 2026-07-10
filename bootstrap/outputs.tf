output "state_bucket_name" {
  value       = aws_s3_bucket.terraform_state.bucket
  description = "Paste into backend.tf -> bucket"
}

output "backend_kms_key_arn" {
  value       = aws_kms_key.terraform_backend.arn
  description = "Paste into backend.tf -> kms_key_id"
}

