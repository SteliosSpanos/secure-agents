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
  - has similar configuration to the main queue but is used for a different purpose
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

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue",
    sourceQueueArns   = [aws_sqs_queue.agent_queue.arn]
  })

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
  policy    = data.aws_iam_policy_document.agent_queue_policy.json
}




// Webhook Dead Letter Queue

resource "aws_sqs_queue" "webhook_dlq" {
  name                              = "${var.project_name}-webhook-dlq"
  message_retention_seconds         = var.sqs_dlq_retention_days * 86400 // 14 days (max allowed)
  kms_master_key_id                 = aws_kms_key.shared.arn
  kms_data_key_reuse_period_seconds = 300

  // Security best practice: only allow the specific source queue to use this DLQ
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue",
    sourceQueueArns   = [aws_sqs_queue.webhook_queue.arn]
  })

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

resource "aws_sqs_queue_policy" "webhook_queue_policy" {
  queue_url = aws_sqs_queue.webhook_queue.id
  policy    = data.aws_iam_policy_document.webhook_queue_policy.json
}




// Webhook Consumer Lambda

data "archive_file" "webhook_consumer_zip" {
  type        = "zip"
  source_file = "../lambda-webhook-consumer/webhook_consumer.py"
  output_path = "webhook_consumer.zip"
}

resource "aws_lambda_function" "webhook_consumer" {
  description      = "Lambda Webhook Consumer to send result to client"
  filename         = data.archive_file.webhook_consumer_zip.output_path
  source_code_hash = data.archive_file.webhook_consumer_zip.output_base64sha256
  function_name    = "${var.project_name}-webhook-consumer"
  role             = aws_iam_role.webhook_consumer_role.arn
  handler          = "webhook_consumer.lambda_handler"
  runtime          = "python3.11"
  timeout          = 15
  memory_size      = 256

  depends_on = [aws_cloudwatch_log_group.webhook_consumer_logs]

  vpc_config {
    subnet_ids = [
      aws_subnet.agents_private_subnet_1.id,
      aws_subnet.agents_private_subnet_2.id
    ]
    security_group_ids = [aws_security_group.webhook_consumer_sg.id]
  }

  environment {}
}

resource "aws_lambda_event_source_mapping" "webhook_consumer" {
  event_source_arn                   = aws_sqs_queue.webhook_queue.arn
  function_name                      = aws_lambda_function.webhook_consumer.arn
  enabled                            = true
  batch_size                         = 10
  maximum_batching_window_in_seconds = 10

  // Prevents the Lambda from scaling out too fast and overwhelming external webhook endpoints
  scaling_config {
    maximum_concurrency = 5
  }

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.webhook_dlq.arn
    }
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
