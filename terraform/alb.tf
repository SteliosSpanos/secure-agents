/*
    Application Load Balancer that lives inside a private subnet
*/

resource "aws_lb" "api_lb" {
  name               = "${var.project_name}-internal-alb"
  internal           = true // No public IP
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets = [
    aws_subnet.agents_private_subnet_1.id,
    aws_subnet.agents_private_subnet_2.id
  ]

  access_logs {
    bucket  = aws_s3_bucket.alb_logs.id
    prefix  = "alb-logs"
    enabled = true
  }

}

// Target Group
// Where to send the traffic and how to check the health

resource "aws_lb_target_group" "api_tg" {
  name        = "${var.project_name}-api-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.agents_vpc.id
  target_type = "ip"

  health_check {
    path                = "/health"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
    matcher             = "200"
  }
}

// Listen on Port 80 (Standard HTTP)

resource "aws_lb_listener" "api_listener" {
  load_balancer_arn = aws_lb.api_lb.arn
  port              = "80"
  protocol          = "HTTP"

  // Any traffic that hits port 80 is immediately forwarded to the target group
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api_tg.arn
  }
}

// S3 Bucket for Logs

resource "aws_s3_bucket" "alb_logs" {
  bucket        = "${var.project_name}-alb-logs-${data.aws_caller_identity.current.account_id}"
  force_destroy = true // false in prod

  tags = {
    Name = "${var.project_name}-alb-logs"
  }
}

resource "aws_s3_bucket_ownership_controls" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id

  rule {
    id     = "expire-old-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }
  }
}

resource "aws_s3_bucket_public_access_block" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  policy = data.aws_iam_policy_document.alb_logs_bucket_policy.json
}
