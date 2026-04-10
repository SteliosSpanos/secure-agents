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

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api_tg.arn
  }
}
