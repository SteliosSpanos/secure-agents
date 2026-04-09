/*
    IAM role and policies for VPC Flow Logs
*/

resource "aws_iam_role" "vpc_flow_log" {
  name               = "${var.project_name}-vpc-flow-log-role"
  assume_role_policy = data.aws_iam_policy_document.vpc_flow_log_assume_role.json
}

resource "aws_iam_role_policy" "vpc_flow_log" {
  name = "${var.project_name}-vpc-flow-log-policy"
  role = aws_iam_role.vpc_flow_log.id

  policy = data.aws_iam_policy_document.vpc_flow_log.json
}
