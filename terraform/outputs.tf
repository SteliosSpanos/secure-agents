output "api_gateway_url" {
  value       = aws_apigatewayv2_api.fastapi_gateway.api_endpoint
  description = "The public URL for the app"
}
