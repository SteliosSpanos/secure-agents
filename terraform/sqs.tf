/*
  SQS Queues, DLQs & Webhook Consumer Pipeline
  
  Contents:
  - Agent Processing Queue: Long-polling SQS queue holding incoming PDF processing tasks. Configured with a 10-minute visibility timeout to accommodate heavy AI workloads, KMS encryption, and a custom resource policy allowing S3 to publish events.
  - Webhook Delivery Queue: Dedicated queue to manage outgoing webhook payloads.
  - Dead Letter Queues (DLQs): Secure, encrypted isolation queues with 14-day max retention periods.
  - Cycle-Free Redrive Logic: Standalone 'redrive_policy' and 'redrive_allow_policy' resources strictly route messages to DLQs after 3 failed processing attempts without causing Terraform circular dependencies.
  - Webhook Consumer Lambda: Packaged inside a private subnet. Triggered directly by the Webhook SQS queue with batching (up to 10), error isolation (ReportBatchItemFailures), and a strict concurrency limit (5) to prevent overwhelming external client endpoints.
  - S3 Event Integration: Automates the processing pipeline by triggering an SQS message the exact moment a '.pdf' is uploaded to the main storage bucket.
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

  tags = {
    Name = "${var.project_name}-work-queue"
  }
}

// Redrive Policy (tell Main Queue to send failures to the DLQ)

resource "aws_sqs_queue_redrive_policy" "agent_queue_redrive" {
  queue_url = aws_sqs_queue.agent_queue.id

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.agent_dlq.arn
    maxReceiveCount     = 3
  })
}

// Redrive Allow Policy (tell DLQ to only accept messages from the Main Queue)

resource "aws_sqs_queue_redrive_allow_policy" "agent_dlq_allow" {
  queue_url = aws_sqs_queue.agent_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue",
    sourceQueueArns   = [aws_sqs_queue.agent_queue.arn]
  })
}

resource "aws_sqs_queue_policy" "agent_queue_policy" {
  queue_url = aws_sqs_queue.agent_queue.id
  policy    = data.aws_iam_policy_document.sqs_agent_queue_policy.json
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

  tags = {
    Name = "${var.project_name}-webhook-queue"
  }
}

// Redrive Policy for Webhook Queue 

resource "aws_sqs_queue_redrive_policy" "webhook_queue_redrive" {
  queue_url = aws_sqs_queue.webhook_queue.id

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.webhook_dlq.arn
    maxReceiveCount     = 3
  })
}

// Redrive Allow Policy for Webhook DLQ 

resource "aws_sqs_queue_redrive_allow_policy" "webhook_dlq_allow" {
  queue_url = aws_sqs_queue.webhook_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue",
    sourceQueueArns   = [aws_sqs_queue.webhook_queue.arn]
  })
}

resource "aws_sqs_queue_policy" "webhook_queue_policy" {
  queue_url = aws_sqs_queue.webhook_queue.id
  policy    = data.aws_iam_policy_document.sqs_webhook_queue_policy.json
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
  runtime          = "python3.13"
  timeout          = 30
  memory_size      = 256

  depends_on = [aws_cloudwatch_log_group.webhook_consumer_logs]

  vpc_config {
    subnet_ids = [
      aws_subnet.agents_private_subnet_1.id,
      aws_subnet.agents_private_subnet_2.id
    ]
    security_group_ids = [aws_security_group.webhook_consumer_sg.id]
  }

  environment {
    variables = {
      API_KEYS_TABLE = aws_dynamodb_table.api_keys.name
      JOBS_TABLE     = aws_dynamodb_table.jobs.name
    }
  }
}

resource "aws_lambda_event_source_mapping" "webhook_consumer" {
  event_source_arn                   = aws_sqs_queue.webhook_queue.arn
  function_name                      = aws_lambda_function.webhook_consumer.arn
  enabled                            = true
  batch_size                         = 10
  maximum_batching_window_in_seconds = 10
  function_response_types            = ["ReportBatchItemFailures"]

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
