/*
    Configuration of inbound and outbound rules of the NACL for the private subnet.
    Takes into account the different AZs.
*/

resource "aws_network_acl" "private" {
  vpc_id = aws_vpc.agents_vpc.id
  subnet_ids = [
    aws_subnet.agents_private_subnet_1.id,
    aws_subnet.agents_private_subnet_2.id
  ]

  tags = {
    Name = "${var.project_name}-private-nacl"
  }
}

// Inbound Rules

resource "aws_network_acl_rule" "private_health_check" {
  network_acl_id = aws_network_acl.private.id
  rule_number    = 100
  rule_action    = "allow"
  protocol       = "tcp"
  cidr_block     = var.vpc_cidr
  from_port      = 8000
  to_port        = 8000
}

resource "aws_network_acl_rule" "private_alb_traffic" {
  network_acl_id = aws_network_acl.private.id
  rule_number    = 110
  rule_action    = "allow"
  protocol       = "tcp"
  cidr_block     = var.vpc_cidr
  from_port      = 80
  to_port        = 80
}

resource "aws_network_acl_rule" "private_https_endpoints" {
  network_acl_id = aws_network_acl.private.id
  rule_number    = 120
  rule_action    = "allow"
  protocol       = "tcp"
  cidr_block     = var.vpc_cidr
  from_port      = 443
  to_port        = 443
}

resource "aws_network_acl_rule" "private_ephemeral" {
  network_acl_id = aws_network_acl.private.id
  rule_number    = 130
  rule_action    = "allow"
  protocol       = "tcp"
  cidr_block     = "0.0.0.0/0"
  from_port      = 1024
  to_port        = 65535
}

// Outbound Rules

resource "aws_network_acl_rule" "private_all_outbound" {
  network_acl_id = aws_network_acl.private.id
  rule_number    = 100
  rule_action    = "allow"
  protocol       = "-1"
  cidr_block     = "0.0.0.0/0"
  from_port      = 0
  to_port        = 0
}
