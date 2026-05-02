/*
    GuardDuty monitors for malicious activity and unauthorized behavior.
*/

resource "aws_guardduty_detector" "main" {
  enable = true

  // S3 Protection
  features {
    name   = "S3_DATA_EVENTS"
    status = "ENABLED"
  }

  // Fargate Runtime Monitoring
  features {
    name   = "RUNTIME_MONITORING"
    status = "ENABLED"

    additional_configuration {
      name   = "EKS_ADDON_MANAGEMENT"
      status = "DISABLED"
    }

    additional_configuration {
      name   = "ECS_FARGATE_AGENT_MANAGEMENT"
      status = "ENABLED"
    }
  }

  tags = {
    Name = "${var.project_name}-guardduty"
  }
}
