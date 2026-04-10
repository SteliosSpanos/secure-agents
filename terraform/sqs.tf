/*
    The SQS configuration that stores S3 event notifications for
    the agent worker to wake up.
    Also the Dead Letter Queue
*/

// Dead Letter Queue

resource "aws_sqs_queue" "agent_dlq" {
  name                              = "${var.project_name}-dlq"
  message_retention_seconds         = var.sqs_dlq_retention_days * 86400 # 14 days (max allowed)
  kms_master_key_id                 = aws_kms_key.agents.arn
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

  kms_master_key_id                 = aws_kms_key.agents.arn
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
