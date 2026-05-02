/*
    GuardDuty monitors for malicious activity and unauthorized behavior.
*/

resource "aws_guardduty_detector" "main" {
  enable = true

  tags = {
    Name = "${var.project_name}-guardduty"
  }
}

// S3 Protection

resource "aws_guardduty_detector_feature" "s3_logs" {
  detector_id = aws_guardduty_detector.main.id
  name        = "S3_DATA_EVENTS"
  status      = "ENABLED"
}

// Fargate Runtime Monitoring

resource "aws_guardduty_detector_feature" "runtime_monitoring" {
  detector_id = aws_guardduty_detector.main.id
  name        = "RUNTIME_MONITORING"
  status      = "ENABLED"

  additional_configuration {
    name   = "EKS_ADDON_MONITORING"
    status = "DISABLED"
  }

  additional_configuration {
    name   = "ECS_FARGATE_AGENT_MANAGEMENT"
    status = "ENABLED"
  }
}
