/*
    API Gateway with VPC link to the ALB and the Lambda authorizer
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
  integration_type   = "HTTP_PROXY"
  integration_uri    = aws_lb_listener.api_listener.arn
  integration_method = "ANY"
  connection_type    = "VPC_LINK"
  connection_id      = aws_apigatewayv2_vpc_link.api_link.id

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
  auto_deploy = true
}

// Lambda Zip Automation
data "archive_file" "authorizer_zip" {
  type        = "zip"
  source_file = "../agent-api/authorizer.py"
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

  environment {
    variables = {
      API_KEYS_TABLE = aws_dynamodb_table.api_keys.name
    }
  }
}

// API Gateway Authorizer

resource "aws_apigatewayv2_authorizer" "lambda_auth" {
  api_id                            = aws_apigatewayv2_api.fastapi_gateway.id
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.authorizer.invoke_arn
  identity_sources                  = ["$request.header.x-api-key"]
  name                              = "lambda-authorizer"
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
}

// Permission for API Gateway to call Lambda

resource "aws_lambda_permission" "api_gw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.fastapi_gateway.execution_arn}/*/*"
}
