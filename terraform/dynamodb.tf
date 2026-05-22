/*
  DynamoDB Tables:
  - API Keys Table: Stores API keys with TTL for expiration and encryption at rest
  - Jobs Table: Stores job information with a composite primary key (client_id, job_id), TTL for cleanup, and encryption at rest
  - Both have point-in-time recovery enabled for data protection
  - A resource policy is attached to both the API Keys table and the Jobs table to restrict access to the VPC endpoint
  - A VPC endpoint is created for DynamoDB
*/

// VPC Endpoint for DynamoDB

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.agents_vpc.id
  service_name      = "com.amazonaws.${var.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.agents_private_rt.id]

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
  hash_key     = "api_key"

  attribute {
    name = "api_key"
    type = "S"
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



// Webhook Lambda 

data "archive_file" "webhook_zip" {
  type        = "zip"
  source_file = "../lambda-webhook/webhook_trigger.py"
  output_path = "webhook_trigger.zip"
}

resource "aws_lambda_function" "webhook_trigger" {
  description      = "Lambda Webhook Trigger to send completion message to webhook service"
  filename         = data.archive_file.webhook_zip.output_path
  source_code_hash = data.archive_file.webhook_zip.output_base64sha256
  function_name    = "${var.project_name}-webhook-trigger"
  role             = aws_iam_role.webhook_trigger_role.arn
  handler          = "webhook_trigger.lambda_handler"
  runtime          = "python3.11"
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
  event_source_arn       = aws_dynamodb_table.jobs.stream_arn
  function_name          = aws_lambda_function.webhook_trigger.arn
  starting_position      = "LATEST" // Only new changes from now on
  batch_size             = 10       // The Lambda event will contain up to 10 records
  maximum_retry_attempts = 3
}
