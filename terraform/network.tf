/*
    Network Architecture: 1 VPC, 2 private subnets(multi-AZ)
    with 1 private route table, VPC Flow Logs and VPC Endpoints
*/

// VPC 

resource "aws_vpc" "agents_vpc" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.project_name}-vpc"
  }
}

// Private Subnets 

resource "aws_subnet" "agents_private_subnet_1" {
  vpc_id            = aws_vpc.agents_vpc.id
  cidr_block        = var.private_subnet_1_cidr
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = {
    Name = "${var.project_name}-private-subnet-1"
  }
}

resource "aws_subnet" "agents_private_subnet_2" {
  vpc_id            = aws_vpc.agents_vpc.id
  cidr_block        = var.private_subnet_2_cidr
  availability_zone = data.aws_availability_zones.available.names[1]

  tags = {
    Name = "${var.project_name}-private-subnet-2"
  }
}

// Private Route Table

resource "aws_route_table" "agents_private_rt" {
  vpc_id = aws_vpc.agents_vpc.id

  tags = {
    Name = "${var.project_name}-private-rt"
  }
}

// Route Table Associations

resource "aws_route_table_association" "agents_private_assoc_1" {
  subnet_id      = aws_subnet.agents_private_subnet_1.id
  route_table_id = aws_route_table.agents_private_rt.id
}

resource "aws_route_table_association" "agents_private_assoc_2" {
  subnet_id      = aws_subnet.agents_private_subnet_2.id
  route_table_id = aws_route_table.agents_private_rt.id
}

// VPC Flow Logs

resource "aws_cloudwatch_log_group" "vpc_flow_logs" {
  name              = "/aws/vpc-flow-logs/${var.project_name}"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.agents.arn

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

// These endpoints cover the 'hidden' dependencies required for Fargate
// 1. ECR, 2. Logs, 3. KMS, 4. SQS, 5. Bedrock

locals {
  services = [
    "ecr.api",
    "ecr.dkr",
    "logs",
    "sqs",
    "kms",
    "sts",
    "bedrock-runtime"
  ]
}

resource "aws_vpc_endpoint" "interfaces" {
  for_each = toset(local.services)

  vpc_id            = aws_vpc.agents_vpc.id
  service_name      = "com.amazonaws.${var.region}.${each.value}"
  vpc_endpoint_type = "Interface"

  subnet_ids = [
    aws_subnet.agents_private_subnet_1.id,
    aws_subnet.agents_private_subnet_2.id
  ]

  security_group_ids  = [aws_security_group.vpc_endpoints_sg.id]
  private_dns_enabled = true

  tags = {
    Name = "${var.project_name}-${each.value}-endpoint"
  }
}
