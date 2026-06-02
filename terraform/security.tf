/*
    Security Groups:
    - VPC Link (ingress: HTTP from APIGW | egress: ALB)
    - ALB (ingress: HTTP from VPC Link | egress: Fargate containers)
    - Fargate API (ingress: HTTP from ALB | egress: HTTPS to VPC Endpoints)
    - Fargate Workers (egress: HTTPS to VPC Endpoints)
    - VPC Endpoints (ingress: HTTPS from Fargate API and Workers)
    - Lambda Authorizer (egress: HTTPS only to DynamoDB Endpoint)
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

// Fargate API 

resource "aws_security_group" "fargate_api_sg" {
  name        = "${var.project_name}-fargate-api-sg"
  description = "Security group for the FastAPI Fargate containers"
  vpc_id      = aws_vpc.agents_vpc.id

  ingress {
    description     = "Allow HTTP from Internal ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  egress { // AWS SDK communicates over HTTPS
    description     = "Allow HTTPS out to VPC endpoints"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.vpc_endpoints_sg.id] // Covers Interface Endpoints
    prefix_list_ids = [                                        // Covers Gateway Endpoints
      data.aws_prefix_list.s3.id,
      data.aws_prefix_list.dynamodb.id
    ]
  }
}

// Fargate Workers

resource "aws_security_group" "fargate_worker_sg" {
  name        = "${var.project_name}-fargate-worker-sg"
  description = "Security group for the AI Agent worker"
  vpc_id      = aws_vpc.agents_vpc.id

  egress {
    description     = "Allow HTTPS out to VPC Endpoints"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.vpc_endpoints_sg.id]
    prefix_list_ids = [
      data.aws_prefix_list.s3.id,
      data.aws_prefix_list.dynamodb.id
    ]
  }
}

// VPC Endpoints

resource "aws_security_group" "vpc_endpoints_sg" {
  name        = "${var.project_name}-endpoints-sg"
  description = "Allow ECS tasks and Lambdas to communicate with AWS Service Endpoints"
  vpc_id      = aws_vpc.agents_vpc.id

  ingress {
    description = "HTTPS from Fargate API, Agent and Lambda Authorizer, Webhook Trigger SGs"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    security_groups = [
      aws_security_group.fargate_api_sg.id,
      aws_security_group.fargate_worker_sg.id,
      aws_security_group.authorizer_sg.id,
      aws_security_group.webhook_trigger_sg.id,
      aws_security_group.webhook_consumer_sg.id,
      aws_security_group.nat_instance.id,
      aws_security_group.jump_box.id
    ]
  }

  tags = {
    Name = "${var.project_name}-endpoints-sg"
  }
}

// Lambda Authorizer

resource "aws_security_group" "authorizer_sg" {
  name        = "${var.project_name}-authorizer-sg"
  description = "Allow Authorizer Lambda to reach DynamoDB Endpoints"
  vpc_id      = aws_vpc.agents_vpc.id

  egress {
    description     = "Allow HTTPS egress to DynamoDB via Gateway Endpoint"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [data.aws_prefix_list.dynamodb.id]
  }

  egress {
    description     = "Allow HTTPS egress to Interface Endpoints (KMS, Logs)"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.vpc_endpoints_sg.id]
  }

  tags = {
    Name = "${var.project_name}-authorizer-sg"
  }
}

// Lambda Webhook Trigger

resource "aws_security_group" "webhook_trigger_sg" {
  name        = "${var.project_name}-webhook-trigger-sg"
  description = "Allow Webhook Trigger Lambda to reach VPC Endpoints"
  vpc_id      = aws_vpc.agents_vpc.id

  // The lambda is actually the one calling the DynamoDB stream
  egress {
    description     = "Allow HTTPS egress to DynamoDB Gateway Endpoint"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [data.aws_prefix_list.dynamodb.id]
  }

  egress {
    description     = "Allow HTTPS egress to Interface Endpoints (KMS, SQS, Logs)"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.vpc_endpoints_sg.id]
  }

  tags = {
    Name = "${var.project_name}-webhook-trigger-sg"
  }
}

// Lambda Webhook Consumer

resource "aws_security_group" "webhook_consumer_sg" {
  name        = "${var.project_name}-webhook-consumer-sg"
  description = "Allow Webhook Consumer Lambda to reach VPC Endpoints and External Webhook Endpoints"
  vpc_id      = aws_vpc.agents_vpc.id

  egress {
    description     = "Allow HTTPS egress to DynamoDB Gateway Endpoint"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [data.aws_prefix_list.dynamodb.id]
  }

  egress {
    description     = "Allow HTTPS egress to Interface Endpoints (KMS, SQS, Logs)"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.vpc_endpoints_sg.id]
  }

  egress {
    description = "Allow HTTPS to External Webhook URLs"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-webhook-consumer-sg"
  }
}

// EC2 Jump Box

resource "aws_security_group" "jump_box" {
  name        = "${var.project_name}-jump-box-sg"
  description = "Security group for jump box instance"
  vpc_id      = aws_vpc.agents_vpc.id

  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["${data.external.my_ip.result.ip}/32"]
  }

  ingress {
    description = "ICMP (ping) from my IP"
    from_port   = -1
    to_port     = -1
    protocol    = "icmp"
    cidr_blocks = ["${data.external.my_ip.result.ip}/32"]
  }

  egress {
    description = "All outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-jump-box-sg"
  }
}

// EC2 NAT Instance

resource "aws_security_group" "nat_instance" {
  name        = "${var.project_name}-nat-instance-sg"
  description = "Security group for NAT instance"
  vpc_id      = aws_vpc.agents_vpc.id

  ingress {
    description     = "HTTPS from Webhook Consumer Lambda"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.webhook_consumer_sg.id]
  }

  ingress {
    description     = "SSH from jump box"
    from_port       = 22
    to_port         = 22
    protocol        = "tcp"
    security_groups = [aws_security_group.jump_box.id]
  }

  ingress {
    description     = "ICMP (ping) from jump box"
    from_port       = -1
    to_port         = -1
    protocol        = "icmp"
    security_groups = [aws_security_group.jump_box.id]
  }

  egress {
    description = "Allow HTTPS to internet for webhooks and updates"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow HTTP to internet for package updates"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow DNS (TCP) to internet"
    from_port   = 53
    to_port     = 53
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow DNS (UDP) to internet"
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-nat-instance-sg"
  }
}
