/*
  KMS Encryption Keys
  - aws_kms_key.api_keys_table: encrypts agents_APIKeys (auth credentials)
  - aws_kms_key.jobs_table: encrypts agents_Jobs (client document data)
  - aws_kms_key.shared: encrypts S3, SQS, Cloudwatch, ECR
  - aws_kms_key.waf_log_key: encrypts WAF logs that are in us-east-1
*/

// API Keys Table Key

resource "aws_kms_key" "api_keys_table" {
  description             = "${var.project_name}-api-keys-table-kms-key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.api_keys_table_kms_policy.json

  tags = {
    Name = "${var.project_name}-api-keys-table-kms-key"
  }
}

resource "aws_kms_alias" "api_keys_table" {
  name          = "alias/${var.project_name}-api-keys-table"
  target_key_id = aws_kms_key.api_keys_table.key_id
}

// Jobs Table Key

resource "aws_kms_key" "jobs_table" {
  description             = "${var.project_name}-jobs-table-kms-key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.jobs_table_kms_policy.json

  tags = {
    Name = "${var.project_name}-jobs-table-kms-key"
  }
}

resource "aws_kms_alias" "jobs_table" {
  name          = "alias/${var.project_name}-jobs-table"
  target_key_id = aws_kms_key.jobs_table.key_id
}

// Shared Key

resource "aws_kms_key" "shared" {
  description             = "${var.project_name}-shared-kms-key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.shared_kms_policy.json

  tags = {
    Name = "${var.project_name}-shared-kms-key"
  }
}

resource "aws_kms_alias" "shared" {
  name          = "alias/${var.project_name}-shared"
  target_key_id = aws_kms_key.shared.key_id
}

// WAF Logs Key

resource "aws_kms_key" "waf_log" {
  description             = "${var.project_name}-waf-log-kms-key"
  provider                = aws.global // Uses us-east-1 provider
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.waf_log_kms_policy.json

  tags = {
    Name = "${var.project_name}-waf-log-kms-key"
  }
}

resource "aws_kms_alias" "waf_log" {
  provider      = aws.global
  name          = "alias/${var.project_name}-waf-log"
  target_key_id = aws_kms_key.waf_log.key_id
}
