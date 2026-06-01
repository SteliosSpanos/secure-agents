/*
  Network Architecture:
  - 1 VPC
  - 2 private subnets(multi-AZ)
  - 1 private route table
  - VPC Endpoints (Interfaces needed for Fargate)
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

// Public Subnets

resource "aws_subnet" "agents_public_subnet_1" {
  vpc_id                  = aws_vpc.agents_vpc.id
  cidr_block              = var.public_subnet_1_cidr
  map_public_ip_on_launch = true
  availability_zone       = data.aws_availability_zones.available.names[0]

  tags = {
    Name = "${var.project_name}-public-subnet-1"
  }
}

resource "aws_subnet" "agents_public_subnet_2" {
  vpc_id                  = aws_vpc.agents_vpc.id
  cidr_block              = var.public_subnet_2_cidr
  map_public_ip_on_launch = true
  availability_zone       = data.aws_availability_zones.available.names[1]

  tags = {
    Name = "${var.project_name}-public-subnet-2"
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

// IGW

resource "aws_internet_gateway" "agents_igw" {
  vpc_id = aws_vpc.agents_vpc.id

  tags = {
    Name = "${var.project_name}-igw"
  }
}

// Private Route Tables

resource "aws_route_table" "agents_private_rt_1" {
  vpc_id = aws_vpc.agents_vpc.id

  tags = {
    Name = "${var.project_name}-private-rt-1"
  }
}

resource "aws_route_table" "agents_private_rt_2" {
  vpc_id = aws_vpc.agents_vpc.id

  tags = {
    Name = "${var.project_name}-private-rt-2"
  }
}

// Public Route Table

resource "aws_route_table" "agents_public_rt" {
  vpc_id = aws_vpc.agents_vpc.id

  tags = {
    Name = "${var.project_name}-public-rt"
  }
}

// Route Table Associations

resource "aws_route_table_association" "agents_private_assoc_1" {
  subnet_id      = aws_subnet.agents_private_subnet_1.id
  route_table_id = aws_route_table.agents_private_rt_1.id
}

resource "aws_route_table_association" "agents_private_assoc_2" {
  subnet_id      = aws_subnet.agents_private_subnet_2.id
  route_table_id = aws_route_table.agents_private_rt_2.id
}

resource "aws_route_table_association" "agents_public_assoc_1" {
  subnet_id      = aws_subnet.agents_public_subnet_1.id
  route_table_id = aws_route_table.agents_public_rt.id
}

resource "aws_route_table_association" "agents_public_assoc_2" {
  subnet_id      = aws_subnet.agents_public_subnet_2.id
  route_table_id = aws_route_table.agents_public_rt.id
}

// Routes

resource "aws_route" "route_to_igw" {
  route_table_id         = aws_route_table.agents_public_rt.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.agents_igw.id
}

resource "aws_route" "private_to_nat_1" {
  route_table_id         = aws_route_table.agents_private_rt_1.id
  destination_cidr_block = "0.0.0.0/0"
  network_interface_id   = aws_instance.nat_instance["az1"].primary_network_interface_id
}

resource "aws_route" "private_to_nat_2" {
  route_table_id         = aws_route_table.agents_private_rt_2.id
  destination_cidr_block = "0.0.0.0/0"
  network_interface_id   = aws_instance.nat_instance["az2"].primary_network_interface_id
}

// These endpoints cover the 'hidden' dependencies required for Fargate

locals {
  services = [
    "ecr.api",
    "ecr.dkr",
    "logs",
    "sqs",
    "kms",
    "sts",
    "bedrock-runtime",
    "ecs-agent",    // Required for GuardDuty ECS_FARGATE_MANAGEMENT
    "ecs-telemetry" // Required for GuardDuty ECS_FARGATE_MANAGEMNT
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
