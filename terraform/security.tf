/*
    Security groups for VPC Link, ALB and Compute
*/

// VPC Link

resource "aws_security_group" "vpc_link_sg" {
  name        = "${var.project_name}-vpc-link-sg"
  description = "Security group for API Gateway VPC Link"
  vpc_id      = aws_vpc.agents_vpc.id

  ingress {
    description = "Allow inbound HTTP from API Gateway"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow outbound to internal ALB only"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.agents_vpc.cidr_block]
  }
}

// ALB

resource "aws_security_group" "alb_sg" {
  name        = "${var.project_name}-alb-sg"
  description = "Security group for Internal ALB"
  vpc_id      = aws_vpc.agents_vpc.id

  ingress {
    description     = "Allow HTTP only from VPC Link"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.vpc_link_sg.id]
  }

  egress {
    description = "Allow outbound to Fargate FastAPI containers"
    from_port   = 8000 // Default FastAPI port
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.agents_vpc.cidr_block]
  }
}
