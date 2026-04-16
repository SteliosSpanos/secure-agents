/*
    DynamoDB tables compatible with the FastAPI app (agents_Jobs, agents_APIKeys)
    and the policies
*/

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
    kms_key_arn = aws_kms_key.agents.arn
  }

  // we can recover any data from any time
  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name = "${var.project_name}-api-keys"
  }
}

// Jobs Table

resource "aws_dynamodb_table" "jobs" {
  name         = "agents_Jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "client_id"
  range_key    = "job_id"

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
    kms_key_arn = aws_kms_key.agents.arn
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
  policy       = data.aws_iam_policy_document.dynamodb_table_policy.json
}

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
