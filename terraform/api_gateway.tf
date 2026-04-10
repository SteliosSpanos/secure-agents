/*
    API Gateway with VPC link to the ALB
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

  cors_configuration {
    allow_origins = ["*"]
    allow_headers = ["Authorization", "Content-Type", "x-api-key"]
  }
}

// Connection to ALB

resource "aws_apigatewayv2_integration" "alb_integration" {
  api_id             = aws_apigatewayv2_api.fastapi_gateway.id
  integration_type   = "HTTP_PROXY"
  integration_uri    = aws_lb_listener.api_listener.arn
  integration_method = "ANY"
  connection_type    = "VPC_LINK"
  connection_id      = aws_apigatewayv2_vpc_link.api_link.id
}

// The "Dumb Pipe" Route

resource "aws_apigatewayv2_route" "default_route" {
  api_id    = aws_apigatewayv2_api.fastapi_gateway.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.alb_integration.id}"
}

// Deploy the stage

resource "aws_apigatewayv2_stage" "default_stage" {
  api_id      = aws_apigatewayv2_api.fastapi_gateway.id
  name        = "$default"
  auto_deploy = true
}
