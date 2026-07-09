/*
  Key Management Service (KMS) Encryption Keys
 
  Contents:
  - API Keys Table Key: Encrypts auth credentials stored in the API Keys DynamoDB table.
  - Jobs Table Key: Encrypts sensitive client document data within the Jobs DynamoDB table.
  - Shared Key: A versatile key utilized for encrypting S3 buckets, SQS queues, ECR repositories, and standard CloudWatch log groups.
  - WAF Log Key: Provisioned specifically in the global region (us-east-1) to encrypt global Web Application Firewall (WAF) logs.
  - EBS Key: Dedicated key to encrypt the Elastic Block Store (EBS) root volumes for the EC2 Jump Boxes and NAT Instances.
  - Security Standards: All keys are provisioned with automated key rotation enabled, a strict 30-day deletion window, custom least-privilege IAM policies, and friendly aliases.
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

// EBS Key

resource "aws_kms_key" "ebs" {
  description             = "${var.project_name}-ebs-kms-key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.ebs_kms_policy.json

  tags = {
    Name = "${var.project_name}-ebs-kms-key"
  }
}

resource "aws_kms_alias" "ebs" {
  name          = "alias/${var.project_name}-ebs"
  target_key_id = aws_kms_key.ebs.key_id
}
