data "aws_caller_identity" "current" {}

// S3 Bucket Policy (Remote Backend)

data "aws_iam_policy_document" "state_force_ssl" {
  statement {
    sid    = "AllowSSLOnly"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.terraform_state.arn,
      "${aws_s3_bucket.terraform_state.arn}/*"
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}
