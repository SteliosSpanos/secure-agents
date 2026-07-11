/*
  Main S3 Storage Bucket, Access Logs & VPC Endpoint
  
  Contents:
  - Storage Bucket: Dedicated bucket for processing documents, with strict public access blocks, versioning enabled, and automated server access logging.
  - Security Controls: Enforces BucketOwner ownership to disable legacy ACLs, applies KMS Server-Side Encryption, and utilizes S3 Bucket Keys to reduce KMS costs.
  - CORS & Lifecycle: Configured to accept POST requests with custom client metadata headers from trusted origins. Lifecycle rules automatically expire data after 30 days and clean up incomplete multipart uploads.
  - S3 Access Logs Bucket: Secure bucket utilizing AES-256 encryption with a 90-day retention policy to capture all traffic hitting the main storage bucket.
  - VPC Gateway Endpoint: Establishes a private connection within the VPC directly to S3. Both the S3 Bucket Policy and Endpoint Policy explicitly restrict traffic to flow exclusively through this internal route.
*/

resource "aws_s3_bucket" "agents" {
  bucket        = "${var.project_name}-storage-${data.aws_caller_identity.current.account_id}"
  force_destroy = true

  /*lifecycle {
    prevent_destroy = true
  }*/

  tags = {
    Name = "${var.project_name}-storage"
  }
}

// Ownership Controls (Disables ACLs)

resource "aws_s3_bucket_ownership_controls" "agents" {
  bucket = aws_s3_bucket.agents.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

// Server Access Logging

resource "aws_s3_bucket_logging" "agents" {
  bucket = aws_s3_bucket.agents.id

  target_bucket = aws_s3_bucket.s3_access_logs.id
  target_prefix = "agents-access-logs/"
}

// CORS Configuration

resource "aws_s3_bucket_cors_configuration" "agents" {
  bucket = aws_s3_bucket.agents.id

  cors_rule {
    allowed_headers = [
      "Content-Type",
      "x-amz-server-side-encryption",
      "x-amz-server-side-encryption-aws-kms-key-id",
      "x-amz-meta-client-id",
      "x-amz-meta-job-id"
    ]
    allowed_methods = ["POST"]
    allowed_origins = var.allowed_origins
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

// Bucket versioning

resource "aws_s3_bucket_versioning" "agents" {
  bucket = aws_s3_bucket.agents.id

  versioning_configuration {
    status = "Enabled"
  }
}

// Restrict public access to the bucket

resource "aws_s3_bucket_public_access_block" "agents" {
  bucket = aws_s3_bucket.agents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

// Configuration of lifecycle of shadow files

resource "aws_s3_bucket_lifecycle_configuration" "agents" {
  bucket = aws_s3_bucket.agents.id

  rule {
    id     = "cleanup-old-version-and-30-day-retention"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    expiration {
      days = 30
    }
  }
}

// Server side encryption

resource "aws_s3_bucket_server_side_encryption_configuration" "agents" {
  bucket = aws_s3_bucket.agents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.shared.arn
    }
    bucket_key_enabled = true
  }
}

// S3 Bucket Policy (Resource-Based)

resource "aws_s3_bucket_policy" "agents" {
  bucket = aws_s3_bucket.agents.id

  policy = data.aws_iam_policy_document.s3_bucket_policy.json

  // Ensure the policy is applied last so it doesn't block other configurations
  depends_on = [
    aws_s3_bucket_versioning.agents,
    aws_s3_bucket_server_side_encryption_configuration.agents,
    aws_s3_bucket_public_access_block.agents,
    aws_s3_bucket_lifecycle_configuration.agents
  ]
}

// VPC Endpoint

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.agents_vpc.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids = [
    aws_route_table.agents_private_rt_1.id,
    aws_route_table.agents_private_rt_2.id,
    aws_route_table.agents_public_rt.id
  ]

  tags = {
    Name = "${var.project_name}-s3-endpoint"
  }
}

resource "aws_vpc_endpoint_policy" "s3_policy" {
  vpc_endpoint_id = aws_vpc_endpoint.s3.id
  policy          = data.aws_iam_policy_document.s3_endpoint_policy.json
}






// S3 Access Logs Bucket

resource "aws_s3_bucket" "s3_access_logs" {
  bucket        = "${var.project_name}-s3-access-logs-${data.aws_caller_identity.current.account_id}"
  force_destroy = true

  tags = {
    Name = "${var.project_name}-s3-access-logs"
  }
}

resource "aws_s3_bucket_ownership_controls" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id

  rule {
    id     = "expire-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }
  }
}

resource "aws_s3_bucket_policy" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id
  policy = data.aws_iam_policy_document.s3_access_logs_policy.json
}
