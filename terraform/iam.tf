/*
  Identity and Access Management (IAM) Roles & Profiles
  
  Contents:
  - ECS Compute Roles:
    * Task Execution Role: Grants the ECS agent permissions to pull ECR images and route logs to CloudWatch.
    * API Task Role: Grants the FastAPI containers specific application-level permissions (e.g., DynamoDB read/write).
    * Agent Task Role: Grants AI workers permissions to read SQS, access Bedrock models, and update job statuses.
  - Lambda Roles (VPC Integrated):
    * Authorizer, Trigger & Consumer Roles: Configured with standard assume-role policies and explicitly attached to the AWS managed 'AWSLambdaVPCAccessExecutionRole' to allow them to create ENIs and execute inside private subnets.
  - EC2 Compute Profiles:
    * Jump Box & NAT Instance Roles: Base EC2 roles wrapped in Instance Profiles to allow secure AWS API interactions (like writing CloudWatch logs) directly from the virtual machines.
  - Telemetry Roles:
    * VPC Flow Log Role: Allows the VPC service to assume this role to publish network traffic logs directly to CloudWatch.
*/

// API Role

resource "aws_iam_role" "api_task_role" {
  name               = "${var.project_name}-api-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
}

resource "aws_iam_role_policy" "api_policy" {
  name   = "${var.project_name}-api-permissions"
  role   = aws_iam_role.api_task_role.id
  policy = data.aws_iam_policy_document.api_iam_policy.json
}

// Agent Task Role 

resource "aws_iam_role" "agent_task_role" {
  name               = "${var.project_name}-agent-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
}

resource "aws_iam_role_policy" "agent_task_policy" {
  name   = "${var.project_name}-agent-task-permissions"
  role   = aws_iam_role.agent_task_role.id
  policy = data.aws_iam_policy_document.agent_iam_policy.json
}

// ECS Execution Role

resource "aws_iam_role" "ecs_execution_role" {
  name               = "${var.project_name}-ecs-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ecs_execution_role_policy" {
  role       = aws_iam_role.ecs_execution_role.id
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

// Lambda Authorizer Permissions

resource "aws_iam_role" "authorizer_role" {
  name               = "${var.project_name}-authorizer-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy" "authorizer_policy" {
  name   = "${var.project_name}-authorizer-policy"
  role   = aws_iam_role.authorizer_role.id
  policy = data.aws_iam_policy_document.authorizer_lambda_iam_policy.json
}

resource "aws_iam_role_policy_attachment" "lambda_vpc_access" {
  role       = aws_iam_role.authorizer_role.id
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

// Lambda Webhook Trigger Permissions

resource "aws_iam_role" "webhook_trigger_role" {
  name               = "${var.project_name}-webhook-trigger-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy" "webhook_trigger_policy" {
  name   = "${var.project_name}-webhook-trigger-policy"
  role   = aws_iam_role.webhook_trigger_role.id
  policy = data.aws_iam_policy_document.webhook_trigger_iam_policy.json
}

resource "aws_iam_role_policy_attachment" "webhook_trigger_vpc_access" {
  role       = aws_iam_role.webhook_trigger_role.id
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

// Lambda Webhook Consumer Permissions

resource "aws_iam_role" "webhook_consumer_role" {
  name               = "${var.project_name}-webhook-consumer-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy" "webhook_consumer_policy" {
  name   = "${var.project_name}-webhook-consumer-policy"
  role   = aws_iam_role.webhook_consumer_role.id
  policy = data.aws_iam_policy_document.webhook_consumer_iam_policy.json
}

resource "aws_iam_role_policy_attachment" "webhook_consumer_vpc_access" {
  role       = aws_iam_role.webhook_consumer_role.id
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"

}

// EC2 Jump Box

resource "aws_iam_role" "jump_box_role" {
  name               = "${var.project_name}-jump-box-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy" "jump_box_policy" {
  name   = "${var.project_name}-jump-box-policy"
  role   = aws_iam_role.jump_box_role.id
  policy = data.aws_iam_policy_document.instance_iam_policy.json
}

resource "aws_iam_instance_profile" "jump_box" {
  name = "${var.project_name}-jump-box-profile"
  role = aws_iam_role.jump_box_role.id
}

// EC2 NAT Instance

resource "aws_iam_role" "nat_instance_role" {
  name               = "${var.project_name}-nat-instance-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy" "nat_instance_policy" {
  name   = "${var.project_name}-nat-instance-policy"
  role   = aws_iam_role.nat_instance_role.id
  policy = data.aws_iam_policy_document.instance_iam_policy.json
}

resource "aws_iam_instance_profile" "nat_instance" {
  name = "${var.project_name}-nat-instance-profile"
  role = aws_iam_role.nat_instance_role.id
}

// VPC Flow Logs

resource "aws_iam_role" "vpc_flow_log" {
  name               = "${var.project_name}-vpc-flow-log-role"
  assume_role_policy = data.aws_iam_policy_document.vpc_flow_log_assume_role.json
}

resource "aws_iam_role_policy" "vpc_flow_log" {
  name = "${var.project_name}-vpc-flow-log-policy"
  role = aws_iam_role.vpc_flow_log.id

  policy = data.aws_iam_policy_document.vpc_flow_log.json
}
