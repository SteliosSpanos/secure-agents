/*
  Main SQS Queue:
  - waits for S3 event notifications when a new PDF is uploaded
  - has a long polling configuration to reduce costs
  - has a visibility timeout of 10 minutes to allow for AI processing
  - is encrypted with a KMS key for security
  - has a redrive policy to move failed messages to a Dead Letter Queue (DLQ) after 3 attempts

  Dead Letter Queue (DLQ):
  - stores messages that failed processing in the main queue after 3 attempts
  - has a retention period of 14 days (max allowed by SQS)
  - is encrypted with the same KMS key for consistency

  Webhook Queue:
  - stores messages for webhook (sending results to client)
  - has similar configuration to the main queue but is used for a different purpose4
  - also has a DLQ for failed webhook messages
  - There is no policy because the permissions are handled by the roles of the webhook service and the lambda

  Webhook DLQ:
  - stores messages that failed processing in the webhook queue after 3 attempts
  - has a retention period of 14 days
  - is encrypted with the same KMS key
*/

// Main Dead Letter Queue

resource "aws_sqs_queue" "agent_dlq" {
  name                              = "${var.project_name}-dlq"
  message_retention_seconds         = var.sqs_dlq_retention_days * 86400 # 14 days (max allowed)
  kms_master_key_id                 = aws_kms_key.shared.arn
  kms_data_key_reuse_period_seconds = 300

  tags = {
    Name = "${var.project_name}-dlq"
  }
}

// Main Work Queue

resource "aws_sqs_queue" "agent_queue" {
  name                       = "${var.project_name}-work-queue"
  delay_seconds              = 0
  max_message_size           = 262144
  message_retention_seconds  = var.sqs_retention_days * 86400
  receive_wait_time_seconds  = 20  // Long polling (cost saving)
  visibility_timeout_seconds = 600 // to allow AI processing

  kms_master_key_id                 = aws_kms_key.shared.arn
  kms_data_key_reuse_period_seconds = 300

  // Link to Dead Letter Queue
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.agent_dlq.arn
    maxReceiveCount     = 3 // if worker failes 3 times move to DLQ
  })

  tags = {
    Name = "${var.project_name}-work-queue"
  }
}

resource "aws_sqs_queue_policy" "agent_queue_policy" {
  queue_url = aws_sqs_queue.agent_queue.id
  policy    = data.aws_iam_policy_document.sqs_queue_policy.json
}




// Webhook Dead Letter Queue

resource "aws_sqs_queue" "webhook_dlq" {
  name                              = "${var.project_name}-webhook-dlq"
  message_retention_seconds         = var.sqs_dlq_retention_days * 86400 // 14 days (max allowed)
  kms_master_key_id                 = aws_kms_key.shared.arn
  kms_data_key_reuse_period_seconds = 300

  tags = {
    Name = "${var.project_name}-webhook-dlq"
  }
}

// Webhook Queue

resource "aws_sqs_queue" "webhook_queue" {
  name                       = "${var.project_name}-webhook-queue"
  delay_seconds              = 0
  max_message_size           = 262144
  message_retention_seconds  = var.sqs_retention_days * 86400
  receive_wait_time_seconds  = 20  // Long polling (cost saving)
  visibility_timeout_seconds = 600 // to allow for processing

  kms_master_key_id                 = aws_kms_key.shared.arn
  kms_data_key_reuse_period_seconds = 300

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.webhook_dlq.arn
    maxReceiveCount     = 3 // if worker failes 3 times move to DLQ
  })

  tags = {
    Name = "${var.project_name}-webhook-queue"
  }
}


// S3 Event Nofification

resource "aws_s3_bucket_notification" "bucket_notification" {
  bucket = aws_s3_bucket.agents.id

  queue {
    queue_arn     = aws_sqs_queue.agent_queue.arn
    events        = ["s3:ObjectCreated:*"]
    filter_suffix = ".pdf"
  }

  // Ensure SQS policy is in place before S3 tries to send
  depends_on = [aws_sqs_queue_policy.agent_queue_policy]
}
