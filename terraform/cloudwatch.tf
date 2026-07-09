/*
  Operational Monitoring, Logging & Alarms Dashboard
  
  Contents:
  - Centralized Logging: Provisions distinct, KMS-encrypted CloudWatch log groups for VPC Flow Logs, ECS Tasks (API & Worker), Lambdas (Authorizer, Trigger, Consumer), WAF, API Gateway, and EC2 Instances (Jump Box & NAT).
  - Alerting System: Deploys an SNS topic (with email subscription) for security and operational alerts, secured by a custom KMS key.
  - SQS Alarms: Triggers when messages enter the Agent or Webhook Dead Letter Queues (DLQs), or if a message is stalled in the main queue for > 20 minutes.
  - Compute & API Alarms: Monitors worker capacity limits, ALB 5XX error rates, high API response latency (> 1s), NAT instance health check failures, and webhook Lambda errors.
  - Threat Detection: EventBridge rule automatically routes high-severity GuardDuty findings (severity >= 7) directly to the SNS alert topic.
  - Central Dashboard: Creates a unified CloudWatch dashboard to visualize real-time API traffic, error rates, and queue backlogs.
*/

// VPC Flow Logs

resource "aws_cloudwatch_log_group" "vpc_flow_logs" {
  name              = "/aws/vpc-flow-logs/${var.project_name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.shared.arn

  tags = {
    Name = "${var.project_name}-vpc-flow-logs"
  }
}

resource "aws_flow_log" "agents_vpc_flow_log" {
  vpc_id               = aws_vpc.agents_vpc.id
  traffic_type         = "ALL"
  iam_role_arn         = aws_iam_role.vpc_flow_log.arn
  log_destination      = aws_cloudwatch_log_group.vpc_flow_logs.arn
  log_destination_type = "cloud-watch-logs"

  tags = {
    Name = "${var.project_name}-vpc-flow-log"
  }
}

// API Logs

resource "aws_cloudwatch_log_group" "api_logs" {
  name              = "/aws/ecs/${var.project_name}-api"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.shared.arn

  tags = {
    Name = "${var.project_name}-api-logs"
  }
}

// Worker Logs

resource "aws_cloudwatch_log_group" "worker_logs" {
  name              = "/aws/ecs/${var.project_name}-worker"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.shared.arn

  tags = {
    Name = "${var.project_name}-worker-logs"
  }
}

// Lambda Authorizer Logs

resource "aws_cloudwatch_log_group" "authorizer_logs" {
  name              = "/aws/lambda/${var.project_name}-authorizer"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.shared.arn

  tags = {
    Name = "${var.project_name}-authorizer-logs"
  }
}

// Lambda Webhook Trigger Logs

resource "aws_cloudwatch_log_group" "webhook_trigger_logs" {
  name              = "/aws/lambda/${var.project_name}-webhook-trigger"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.shared.arn

  tags = {
    Name = "${var.project_name}-webhook-trigger-logs"
  }
}

// Lambda Webhook Consumer Logs

resource "aws_cloudwatch_log_group" "webhook_consumer_logs" {
  name              = "/aws/lambda/${var.project_name}-webhook-consumer"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.shared.arn

  tags = {
    Name = "${var.project_name}-webhook-consumer-logs"
  }
}

// WAF Logs (must be in us-east-1 for Cloudfront and name must start with aws-waf-logs-)

resource "aws_cloudwatch_log_group" "waf_logs" {
  provider          = aws.global
  name              = "aws-waf-logs-${var.project_name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.waf_log.arn

  tags = {
    Name = "${var.project_name}-waf-logs"
  }
}

// API Gateway Logs

resource "aws_cloudwatch_log_group" "api_gateway_logs" {
  name              = "/aws/apigateway/${var.project_name}-apigw"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.shared.arn

  tags = {
    Name = "${var.project_name}-apigw-logs"
  }
}

// Jump Box Logs

resource "aws_cloudwatch_log_group" "jump_box_logs" {
  name              = "/aws/ec2/${var.project_name}-jump-box"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.shared.arn

  tags = {
    Name = "${var.project_name}-jump-box-logs"
  }
}

// NAT Instance Logs

resource "aws_cloudwatch_log_group" "nat_instance_logs" {
  name              = "/aws/ec2/${var.project_name}-nat-instance"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.shared.arn

  tags = {
    Name = "${var.project_name}-nat-instance-logs"
  }
}






// SNS Alerts

resource "aws_sns_topic" "alerts" {
  name              = "${var.project_name}-alerts"
  kms_master_key_id = aws_kms_key.shared.arn

  tags = {
    Name = "${var.project_name}-security-alerts"
  }
}

resource "aws_sns_topic_subscription" "dev_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.email
}

resource "aws_sns_topic_policy" "alerts_policy" {
  arn    = aws_sns_topic.alerts.arn
  policy = data.aws_iam_policy_document.event_bridge_sns_policy.json
}






// Agent DLQ Alarm

resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "${var.project_name}-dlq-alarm"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 1
  alarm_description   = "Fires when an AI agent failes to process a PDF 3 times"

  dimensions = {
    QueueName = aws_sqs_queue.agent_dlq.name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

// Webhook DLQ Alarm

resource "aws_cloudwatch_metric_alarm" "webhook_dlq_not_empty" {
  alarm_name          = "${var.project_name}-webhook-dlq-alarm"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 1
  alarm_description   = "Fires when webhook delivery fails permanently"

  dimensions = {
    QueueName = aws_sqs_queue.webhook_dlq.name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

// Worker Max Capacity Alarm

resource "aws_cloudwatch_metric_alarm" "worker_at_max_capacity" {
  alarm_name          = "${var.project_name}-worker-at-max-capacity"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "RunningTaskCount"
  namespace           = "AWS/ContainerInsights"
  period              = 60
  statistic           = "Average"
  threshold           = local.worker_max_capacity
  treat_missing_data  = "notBreaching"
  alarm_description   = "Queue may be backing up faster than workers can drain it"

  dimensions = {
    ClusterName = aws_ecs_cluster.agents_cluster.name
    ServiceName = aws_ecs_service.worker_service.name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

// SQS Stalling (Oldest Message)

resource "aws_cloudwatch_metric_alarm" "sqs_stalling" {
  alarm_name          = "${var.project_name}-sqs-stalling"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 1200
  alarm_description   = "A message has been waiting for > 20 mins. Check worker health"

  dimensions = {
    QueueName = aws_sqs_queue.agent_queue.name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

// ALB High 5XX Error Rate

resource "aws_cloudwatch_metric_alarm" "alb_high_5xx" {
  alarm_name          = "${var.project_name}-alb-high-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "High 5XX error rate from FastAPI containers"

  dimensions = {
    LoadBalancer = aws_lb.api_lb.arn_suffix
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

// ALB High Latency

resource "aws_cloudwatch_metric_alarm" "alb_latency" {
  alarm_name          = "${var.project_name}-alb-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Average"
  threshold           = 1.0
  alarm_description   = "API response time is over 1 second"

  dimensions = {
    LoadBalancer = aws_lb.api_lb.arn_suffix
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

// NAT Instance Health Checks

resource "aws_cloudwatch_metric_alarm" "nat_status_check" {
  for_each            = aws_instance.nat_instance
  alarm_name          = "${var.project_name}-nat-down-${each.key}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "NAT Instance in ${each.key} failed status check"

  dimensions = {
    InstanceId = each.value.id
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

// Webhook Lambda Failures

resource "aws_cloudwatch_metric_alarm" "webhook_lambda_failures" {
  alarm_name          = "${var.project_name}-webhook-failures"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Webhook Lambda failed. Possible NAT Instane or external API issue"

  dimensions = {
    FunctionName = "${var.project_name}-webhook-consumer"
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

// EventBridge for GuardDuty

resource "aws_cloudwatch_event_rule" "guardduty_finding" {
  name        = "${var.project_name}-guardduty-finding"
  description = "Triggers when GuardDuty detects a High-Severity threat"

  event_pattern = jsonencode({
    source      = ["aws.guardduty"]
    detail-type = ["GuardDuty Finding"]
    detail = {
      severity = [{ numeric = [">=", 7] }]
    }
  })
}

resource "aws_cloudwatch_event_target" "sns" {
  rule      = aws_cloudwatch_event_rule.guardduty_finding.name
  target_id = "SendToSNS"
  arn       = aws_sns_topic.alerts.arn
}







// Operational Dashboard

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project_name}-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.api_lb.arn_suffix, { "id" : "m1", "label" : "API Requests" }],
            [".", "HTTPCode_Target_5XX_Count", ".", ".", { "id" : "m2", "label" : "5XX Errors", "color" : "#d62728" }]
          ]
          period = 300
          stat   = "Sum"
          region = var.region
          title  = "API Traffic & Health"
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.agent_queue.name, { "label" : "Tasks Waiting" }],
            [".", "ApproximateNumberOfMessagesNotVisible", ".", ".", { "label" : "Tasks in progress" }],
            [".", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.webhook_queue.name, { "label" : "Webhooks waiting" }]
          ]
          period = 60
          stat   = "Maximum"
          region = var.region
          title  = "Queue Backlogs"
        }
      }
    ]
  })
}

