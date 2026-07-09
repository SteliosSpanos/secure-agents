/*
  DynamoDB Tables, VPC Endpoints & Stream-Triggered Webhooks
  
  Contents:
  - DynamoDB Gateway VPC Endpoint: Configures private route table paths and endpoints policies for isolated data access within the VPC.
  - API Keys Table: Uses 'client_id' as the partition key, attaches a specialized GSI ('ApiKeyIndex') for key validation, applies a custom KMS encryption key, enables TTL data-pruning, and enforces a strict VPC-only resource policy.
  - Jobs Table: Implements a composite primary key ('client_id' and 'job_id') with DynamoDB Streams enabled ('NEW_AND_OLD_IMAGES'), dedicated KMS encryption, PITR protection, and localized network access restrictions via resource policy.
  - Webhook Trigger Lambda: Packaged via automated zip creation and deployed within private subnets to safely receive stream events.
  - Event Source Mapping: Hooks directly into the Jobs DynamoDB Stream, processing batches up to 10 records with built-in batch-bisecting error isolation, explicitly filtered to invoke only on 'MODIFY' events transitioning to a 'COMPLETED' status.
*/

// VPC Endpoint for DynamoDB

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.agents_vpc.id
  service_name      = "com.amazonaws.${var.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids = [
    aws_route_table.agents_private_rt_1.id,
    aws_route_table.agents_private_rt_2.id
  ]

  tags = {
    Name = "${var.project_name}-dynamodb-endpoint"
  }
}

resource "aws_vpc_endpoint_policy" "dynamodb_policy" {
  vpc_endpoint_id = aws_vpc_endpoint.dynamodb.id
  policy          = data.aws_iam_policy_document.dynamodb_endpoint_policy.json
}

// API Keys Table

resource "aws_dynamodb_table" "api_keys" {
  name         = "agents_APIKeys"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "client_id"

  attribute {
    name = "client_id"
    type = "S"
  }

  attribute {
    name = "api_key"
    type = "S"
  }

  global_secondary_index {
    name               = "ApiKeyIndex"
    hash_key           = "api_key"
    projection_type    = "INCLUDE"
    non_key_attributes = ["active"]
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.api_keys_table.arn
  }

  // we can recover any data from any time
  point_in_time_recovery {
    enabled = true
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Name = "${var.project_name}-api-keys"
  }
}

resource "aws_dynamodb_resource_policy" "api_keys_policy" {
  resource_arn = aws_dynamodb_table.api_keys.arn
  policy       = data.aws_iam_policy_document.api_keys_table_policy.json
}

// Jobs Table

resource "aws_dynamodb_table" "jobs" {
  name         = "agents_Jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "client_id"
  range_key    = "job_id"

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "client_id"
    type = "S"
  }

  attribute {
    name = "job_id"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.jobs_table.arn
  }

  point_in_time_recovery {
    enabled = true
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Name = "${var.project_name}-jobs"
  }
}

resource "aws_dynamodb_resource_policy" "jobs_policy" {
  resource_arn = aws_dynamodb_table.jobs.arn
  policy       = data.aws_iam_policy_document.jobs_table_policy.json
}



// Webhook Trigger Lambda 

data "archive_file" "webhook_trigger_zip" {
  type        = "zip"
  source_file = "../lambda-webhook-trigger/webhook_trigger.py"
  output_path = "webhook_trigger.zip"
}

resource "aws_lambda_function" "webhook_trigger" {
  description      = "Lambda Webhook Trigger to send completion message to webhook service"
  filename         = data.archive_file.webhook_trigger_zip.output_path
  source_code_hash = data.archive_file.webhook_trigger_zip.output_base64sha256
  function_name    = "${var.project_name}-webhook-trigger"
  role             = aws_iam_role.webhook_trigger_role.arn
  handler          = "webhook_trigger.lambda_handler"
  runtime          = "python3.13"
  timeout          = 15
  memory_size      = 256

  depends_on = [aws_cloudwatch_log_group.webhook_trigger_logs]

  vpc_config {
    subnet_ids = [
      aws_subnet.agents_private_subnet_1.id,
      aws_subnet.agents_private_subnet_2.id
    ]
    security_group_ids = [aws_security_group.webhook_trigger_sg.id]
  }

  environment {
    variables = {
      WEBHOOK_QUEUE_URL = aws_sqs_queue.webhook_queue.id
    }
  }
}

resource "aws_lambda_event_source_mapping" "webhook_trigger" {
  event_source_arn               = aws_dynamodb_table.jobs.stream_arn
  function_name                  = aws_lambda_function.webhook_trigger.arn
  starting_position              = "LATEST" // Only new changes from now on
  batch_size                     = 10       // The Lambda event will contain up to 10 records
  maximum_retry_attempts         = 3
  bisect_batch_on_function_error = true // Isolates poison pill records

  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["MODIFY"]
        dynamodb = {
          NewImage = { status = { S = ["COMPLETED"] } }
        }
      })
    }
  }
}
