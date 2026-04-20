/*
    API Gateway with VPC link to the ALB and the Lambda
*/

// VPC Link

resource "aws_apigatewayv2_vpc_link" "api_link" {
  name               = "${var.project_name}-vpc-link"
  security_group_ids = [aws_security_group.vpc_link_sg.id]
  subnet_ids = [
    aws_subnet.agents_private_subnet_1.id,
    aws_subnet.agents_private_subnet_2.id
  ]
}

// Public HTTP API

resource "aws_apigatewayv2_api" "fastapi_gateway" {
  name          = "${var.project_name}-gateway"
  protocol_type = "HTTP"
}

// Connection to ALB

resource "aws_apigatewayv2_integration" "alb_integration" {
  api_id             = aws_apigatewayv2_api.fastapi_gateway.id
  integration_type   = "HTTP_PROXY" // Pass the client's request exactly as is to the backend
  integration_uri    = aws_lb_listener.api_listener.arn
  integration_method = "ANY"
  connection_type    = "VPC_LINK"
  connection_id      = aws_apigatewayv2_vpc_link.api_link.id

  // It takes the client_id returned by your Lambda and injects it into the HTTP header as x-client-id
  request_parameters = {
    "overwrite:header.x-client-id" = "$context.authorizer.client_id"
  }
}

// The "Dumb Pipe" Route

resource "aws_apigatewayv2_route" "default_route" {
  api_id    = aws_apigatewayv2_api.fastapi_gateway.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.alb_integration.id}"

  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.lambda_auth.id
}

// Deploy the stage

resource "aws_apigatewayv2_stage" "default_stage" {
  api_id      = aws_apigatewayv2_api.fastapi_gateway.id
  name        = "$default"
  auto_deploy = true // Every time you change a route, it instantly pushes the changes live

  // Rate limiting
  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 100
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway_logs.arn
    format = jsonencode({
      requestId     = "$context.requestId"
      edgeIp        = "$context.identity.sourceIp"
      forwardedIp   = "$request.header.x-forwarded-for"
      trueViewer    = "$request.header.CloudFront-Viewer-Address"
      httpMethod    = "$context.httpMethod"
      status        = "$context.status"
      authorizer_id = "$context.authorizer.client_id"
    })
  }
}

// Lambda Zip Automation

data "archive_file" "authorizer_zip" {
  type        = "zip"
  source_file = "../lambda-authorizer/authorizer.py"
  output_path = "authorizer.zip"
}

// Lambda Function

resource "aws_lambda_function" "authorizer" {
  filename         = data.archive_file.authorizer_zip.output_path
  source_code_hash = data.archive_file.authorizer_zip.output_base64sha256
  function_name    = "${var.project_name}-authorizer"
  role             = aws_iam_role.authorizer_role.arn
  handler          = "authorizer.lambda_handler"
  runtime          = "python3.11"
  timeout          = 15
  memory_size      = 256

  depends_on = [aws_cloudwatch_log_group.authorizer_logs]

  vpc_config {
    subnet_ids = [
      aws_subnet.agents_private_subnet_1.id,
      aws_subnet.agents_private_subnet_2.id
    ]
    security_group_ids = [aws_security_group.authorizer_lambda_sg.id]
  }

  environment {
    variables = {
      API_KEYS_TABLE = aws_dynamodb_table.api_keys.name
      ORIGIN_SECRET  = random_password.origin_secret.result
    }
  }
}

// API Gateway Authorizer

resource "aws_apigatewayv2_authorizer" "lambda_auth" {
  api_id                            = aws_apigatewayv2_api.fastapi_gateway.id
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.authorizer.invoke_arn
  identity_sources                  = ["$request.header.x-api-key", "$request.header.x-origin-verify"] // Don't start the lambda if critical headers are missing
  name                              = "lambda-authorizer"
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  authorizer_result_ttl_in_seconds  = 0
}

// Permission for API Gateway to call Lambda

resource "aws_lambda_permission" "api_gw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.fastapi_gateway.execution_arn}/*/*"
}
