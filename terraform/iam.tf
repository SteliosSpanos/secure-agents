/*
    IAM roles and policies for compute
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

