/*
    The setup for the ECS Fargate FastAPI app
*/

// ECS Cluster & Logging

resource "aws_ecs_cluster" "agents_cluster" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "api_logs" {
  name              = "/ecs/${var.project_name}/api"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.agents.arn
}

// Task Definition

resource "aws_ecs_task_definition" "api_task" {
  family                   = "${var.project_name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512

  execution_role_arn = aws_iam_role.ecs_execution_role.arn
  task_role_arn      = aws_iam_role.api_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "fastapi-container"
      image     = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com/${var.project_name}-api:latest"
      essential = true

      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "PROJECT_NAME", value = var.project_name },
        { name = "DYNAMODB_JOBS_TABLE", value = aws_dynamodb_table.jobs.name },
        { name = "DYNAMODB_KEYS_TABLE", value = aws_dynamodb_table.api_keys.name },
        { name = "S3_BUCKET_NAME", value = aws_s3_bucket.agents.id },
        { name = "SQS_QUEUE_URL", value = aws_sqs_queue.agent_queue.id }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api_logs.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "fastapi"
        }
      }
    }
  ])
}

// ECS Service

resource "aws_ecs_service" "api_service" {
  name            = "${var.project_name}-api-service"
  cluster         = aws_ecs_cluster.agents_cluster.id
  task_definition = aws_ecs_task_definition.api_task.arn
  launch_type     = "FARGATE"

  desired_count = 2

  network_configuration {
    subnets = [
      aws_subnet.agents_private_subnet_1.id,
      aws_subnet.agents_private_subnet_2.id
    ]
    security_groups  = [aws_security_group.fargate_api_sg.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api_tg.arn
    container_name   = "fastapi-container"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.api_listener]
}
