data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

// S3 Bucket Policy (Remote Backend)

data "aws_iam_policy_document" "state_force_ssl" {
  statement {
    sid    = "DenyNonSSLTransport"
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

// S3 Bucket Policy (Main Bucket)

data "aws_iam_policy_document" "s3_bucket_policy" {
  statement {
    sid    = "DenyNonSSLTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.agents.arn,
      "${aws_s3_bucket.agents.arn}/*"
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  // Allow the agent to access S3 only via the VPC endpoint
  statement {
    sid    = "RestrictAgentToVPCEndpoint"
    effect = "Deny"
    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.agent_task_role.arn]
    }
    actions = [
      "s3:GetObject",
      "s3:PutObject"
    ]
    resources = ["${aws_s3_bucket.agents.arn}/*"]
    condition {
      test     = "StringNotEquals"
      variable = "aws:SourceVpce"
      values   = [aws_vpc_endpoint.s3.id]
    }
  }
}

// S3 Endpoint Policy

data "aws_iam_policy_document" "s3_endpoint_policy" {
  statement {
    sid    = "AllowAccessToSpecificBucket"
    effect = "Allow"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = [
      "s3:GetObject",
      "s3:PutObject"
    ]
    resources = [
      aws_s3_bucket.agents.arn,
      "${aws_s3_bucket.agents.arn}/*"
    ]
    condition {
      test     = "StringEquals"
      variable = "aws:PrincipalAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}






// KMS Resource-Based Key Policy

data "aws_iam_policy_document" "kms_key_policy" {
  statement {
    sid    = "KeyAdministrator"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = [data.aws_caller_identity.current.arn]
    }
    actions = [
      "kms:Create*",
      "kms:Describe*",
      "kms:Enable*",
      "kms:List*",
      "kms:Put*",
      "kms:Update*",
      "kms:Revoke*",
      "kms:Disable*",
      "kms:Get*",
      "kms:Delete*",
      "kms:TagResource",
      "kms:UntagResource",
      "kms:ScheduleKeyDeletion",
      "kms:CancelKeyDeletion"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "KeyUsage"
    effect = "Allow"
    principals {
      type = "AWS"
      identifiers = [
        aws_iam_role.api_task_role.arn,
        aws_iam_role.agent_task_role.arn
      ]
    }
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "AllowCloudWatchLogs"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["logs.${var.region}.amazonaws.com"]
    }
    actions = [
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
      "kms:ReEncrypt*"
    ]
    resources = ["*"]
    condition { // Check if the logs belong to MY account
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/${var.project_name}*"]
    }
  }

  statement {
    sid    = "AllowS3ToEncryptSQSMessages"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
    actions = [
      "kms:GenerateDataKey",
      "kms:Decrypt"
    ]
    resources = ["*"]
  }
}







// VPC Flow Log Assume Role Policy

data "aws_iam_policy_document" "vpc_flow_log_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:vpc/${aws_vpc.agents_vpc.id}"]
    }
  }
}

// VPC Flow Log Policy

data "aws_iam_policy_document" "vpc_flow_log" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams"
    ]
    resources = [
      aws_cloudwatch_log_group.vpc_flow_logs.arn,
      "${aws_cloudwatch_log_group.vpc_flow_logs.arn}:*"
    ]
  }
}








// DynamoDB Endpoint Policy

data "aws_iam_policy_document" "dynamodb_endpoint_policy" {
  statement {
    sid    = "AllowAccessToSpecificTables"
    effect = "Allow"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem"
    ]
    resources = [
      aws_dynamodb_table.api_keys.arn,
      aws_dynamodb_table.jobs.arn
    ]
    condition {
      test     = "StringEquals"
      variable = "aws:PrincipalAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}






// ECS Assume Role Policy

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:*"]
    }
  }
}

// API Task Policy

data "aws_iam_policy_document" "api_iam_policy" {
  statement {
    sid    = "DynamoDBKeyVerification"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem"
    ]
    resources = [
      aws_dynamodb_table.api_keys.arn,
      aws_dynamodb_table.jobs.arn
    ]
  }

  statement {
    sid       = "SQSWorkQueue"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.agent_queue.arn]
  }

  statement {
    sid    = "KMSUsage"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey*"
    ]
    resources = [aws_kms_key.agents.arn]
  }

  statement {
    sid       = "S3PresignedPost"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.agents.arn}/*"]
  }
}

// Agent Task Policy


data "aws_iam_policy_document" "agent_iam_policy" {
  statement {
    sid    = "DynamoDBUpdate"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:UpdateItem"
    ]
    resources = [aws_dynamodb_table.jobs.arn]
  }

  statement {
    sid    = "S3Processing"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject"
    ]
    resources = ["${aws_s3_bucket.agents.arn}/*"]
  }

  statement {
    sid    = "SQSReadQueue"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes"
    ]
    resources = [aws_sqs_queue.agent_queue.arn]
  }

  statement {
    sid       = "BedrockAccess"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel"]
    resources = ["arn:aws:bedrock:${var.region}::foundation-model/*"]
  }

  statement {
    sid    = "KMSUsage"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:GenerateDataKey*"
    ]
    resources = [aws_kms_key.agents.arn]
  }
}






// SQS Queue Policy

data "aws_iam_policy_document" "sqs_queue_policy" {
  statement {
    sid    = "AllowS3ToSendMessage"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.agent_queue.arn]
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.agents.arn]
    }
  }

  statement {
    sid    = "AllowComputeUsage"
    effect = "Allow"
    principals {
      type = "AWS"
      identifiers = [
        aws_iam_role.agent_task_role.arn,
        aws_iam_role.api_task_role.arn
      ]
    }
    actions = [
      "sqs:SendMessage",
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility"
    ]
    resources = [aws_sqs_queue.agent_queue.arn]
  }
}








// Lambda (for API Gateway)

data "aws_iam_policy_document" "authorizer_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "authorizer_iam_policy" {
  statement {
    effect    = "Allow"
    actions   = ["dynamodb:GetItem"]
    resources = [aws_dynamodb_table.api_keys.arn]
  }

  statement {
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.agents.arn]
  }

  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["arn:aws:logs:*:*:*"]
  }
}
