/*
    All the Log Groups and VPC Flow Log
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

// Lambda Logs

resource "aws_cloudwatch_log_group" "authorizer_logs" {
  name              = "/aws/lambda/${var.project_name}-authorizer"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.shared.arn

  tags = {
    Name = "${var.project_name}-authorizer-logs"
  }
}

// API Gateway Logs

resource "aws_cloudwatch_log_group" "api_gateway_logs" {
  name              = "/aws/apigateway/${var.project_name}-logs"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.shared.arn

  tags = {
    Name = "${var.project_name}-apigw-logs"
  }
}

// SQS Alerts

resource "aws_sns_topic" "alerts" {
  name              = "${var.project_name}-alerts"
  kms_master_key_id = aws_kms_key.shared.arn
}

resource "aws_sns_topic_subscription" "dev_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.email
}

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
