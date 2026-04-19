/*
    The setup for the ECS Fargate FastAPI app and AI agent worker
*/

// ECS Cluster & Logging

resource "aws_ecs_cluster" "agents_cluster" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

// API Task Definition 

resource "aws_ecs_task_definition" "api_task" {
  family                   = "${var.project_name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512

  execution_role_arn = aws_iam_role.ecs_execution_role.arn
  task_role_arn      = aws_iam_role.api_task_role.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "fastapi-container"
      image     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "AWS_REGION", value = var.region },
        { name = "DYNAMODB_JOBS_TABLE", value = aws_dynamodb_table.jobs.name },
        { name = "S3_BUCKET_NAME", value = aws_s3_bucket.agents.id },
        { name = "ALLOWED_ORIGINS", value = var.allowed_origins },
        { name = "KMS_KEY_ARN", value = aws_kms_key.shared.arn }
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

// Worker Task Definition

resource "aws_ecs_task_definition" "worker_task" {
  family                   = "${var.project_name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024

  execution_role_arn = aws_iam_role.ecs_execution_role.arn
  task_role_arn      = aws_iam_role.agent_task_role.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "agent-worker"
      image     = "${aws_ecr_repository.worker.repository_url}:${var.image_tag}"
      essential = true
      environment = [
        { name = "AWS_REGION", value = var.region },
        { name = "SQS_QUEUE_URL", value = aws_sqs_queue.agent_queue.id },
        { name = "DYNAMODB_JOBS_TABLE", value = aws_dynamodb_table.jobs.name },
        { name = "BEDROCK_MODEL_ID", value = var.bedrock_model_id }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker_logs.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])
}



// API ECS Service

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

  depends_on = [
    aws_lb_listener.api_listener,
    null_resource.api_bootstrap_image
  ]
}

// Worker ECS Service

resource "aws_ecs_service" "worker_service" {
  name            = "${var.project_name}-worker-service"
  cluster         = aws_ecs_cluster.agents_cluster.id
  task_definition = aws_ecs_task_definition.worker_task.arn
  launch_type     = "FARGATE"

  desired_count = 0 # Managed by auto-scaling

  network_configuration {
    subnets = [
      aws_subnet.agents_private_subnet_1.id,
      aws_subnet.agents_private_subnet_2.id
    ]
    security_groups  = [aws_security_group.fargate_worker_sg.id]
    assign_public_ip = false
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  depends_on = [null_resource.worker_bootstrap_image]
}
