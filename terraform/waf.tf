/*
  Web Application Firewall (WAFv2) & Global Threat Protection
  
  Contents:
  - Global Edge Deployment: Provisioned via the global provider (us-east-1) to attach directly to the CloudFront distribution, blocking threats at the AWS edge.
  - Rate Limiting Defenses:
    * Global Limit: Mitigates general volumetric DDoS attacks by blocking any individual IP exceeding 500 requests per 5-minute window.
    * Endpoint Limit: Uses a scoped-down byte match statement to explicitly protect the '/api/v1/request-upload' URI, strictly capping traffic to 100 requests per 5-minute window per IP.
  - Managed Threat Intelligence:
    * Common Rule Set: Automatically mitigates broad, common vulnerabilities (including OWASP Top 10, SQLi, and XSS).
    * Known Bad Inputs Set: Intercepts and blocks requests containing explicitly malformed, invalid, or malicious data patterns.
  - Observability & Telemetry: Enables CloudWatch metrics and request sampling on the main ACL and every individual rule. Connects a dedicated logging configuration to stream full WAF security events directly to a centralized CloudWatch Log Group.
*/

resource "aws_wafv2_web_acl" "api_waf" {
  provider = aws.global

  name        = "${var.project_name}-waf"
  description = "WAF for Cloudfront with Rate Limiting and Manged Rules"
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  # Global Rate Limit
  rule {
    name     = "GlobalRateLimit"
    priority = 1
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 500
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "GlobalRateLimitMetric"
      sampled_requests_enabled   = true
    }
  }

  # Tighter Rate Limit for Upload Requests
  rule {
    name     = "UploadRateLimit"
    priority = 2
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 100
        aggregate_key_type = "IP"
        scope_down_statement {
          byte_match_statement {
            field_to_match {
              uri_path {}
            }
            positional_constraint = "EXACTLY"
            search_string         = "/api/v1/request-upload"
            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "UploadRateLimitMetric"
      sampled_requests_enabled   = true
    }
  }

  // AWS Managed Rules (SQLi, XSS, etc)
  rule {
    name     = "AWSManagedRulesCommon"
    priority = 3
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "CommonRulesMetric"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSManagedRulesKnownBadInputs"
    priority = 4
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "KnownBadInputsMetric"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "GlobalWafMetric"
    sampled_requests_enabled   = true
  }
}

// WAF Logging Configuration

resource "aws_wafv2_web_acl_logging_configuration" "waf_logging" {
  provider                = aws.global
  log_destination_configs = [aws_cloudwatch_log_group.waf_logs.arn]
  resource_arn            = aws_wafv2_web_acl.api_waf.arn
}
