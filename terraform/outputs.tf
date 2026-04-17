output "api_gateway_url" {
  value       = aws_apigatewayv2_api.fastapi_gateway.api_endpoint
  description = "The public URL for the app (internal gateway)"
}

output "cloudfront_url" {
  value       = "https://${aws_cloudfront_distribution.api_dist.domain_name}"
  description = "The public CloudFront URL for the app (with WAF protection)"
}
