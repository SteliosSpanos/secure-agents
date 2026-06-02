/*
    ECS Fargate FastAPI app and AI agent worker:
    - ECS Cluster with Container Insights enabled for monitoring
    - API Task Definition with 256 CPU units and 512 MB memory, using the API
    - Worker Task Definition with 512 CPU units and 1024 MB memory for AI processing
    - Both tasks use Fargate launch type and are deployed in private subnets
    - The ALB lives infront of the API service, while the worker service is internal only
    - Both tasks have IAM roles with least privilege permissions
    - Both services have logging configured to CloudWatch Logs
    - Agent worker has auto-scaling configured 
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

      // Maximize graceful shutdown for Fargate worker
      stopTimeout = 120

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


// EC2 Jump Box

resource "aws_key_pair" "agents_key" {
  key_name   = "${var.project_name}-key"
  public_key = file("${path.module}/${var.public_key_path}")

  tags = {
    Name = "${var.project_name}-key"
  }
}


resource "aws_instance" "jump_box" {
  for_each = {
    "az1" = aws_subnet.agents_public_subnet_1.id
    "az2" = aws_subnet.agents_public_subnet_2.id
  }

  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = var.instance_types.jump_box
  associate_public_ip_address = true
  subnet_id                   = each.value
  vpc_security_group_ids      = [aws_security_group.jump_box.id]
  iam_instance_profile        = aws_iam_instance_profile.jump_box.name
  key_name                    = aws_key_pair.agents_key.key_name

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_size           = 8
    volume_type           = "gp3"
    encrypted             = true
    kms_key_id            = aws_kms_key.ebs.arn
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/userdata-jump-box.tpl", {
    log_group_name = aws_cloudwatch_log_group.jump_box_logs.name
  })
  user_data_replace_on_change = true

  tags = {
    Name = "${var.project_name}-jump-box-${each.key}"
  }
}

resource "aws_eip" "jump_box" {
  for_each = aws_instance.jump_box
  domain   = "vpc"
  instance = each.value.id

  depends_on = [aws_internet_gateway.agents_igw]

  tags = {
    Name = "${var.project_name}-jump-box-eip-${each.key}"
  }
}

// ECS NAT Instance

resource "aws_instance" "nat_instance" {
  for_each = {
    "az1" = aws_subnet.agents_public_subnet_1.id
    "az2" = aws_subnet.agents_public_subnet_2.id
  }

  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = var.instance_types.nat_instance
  associate_public_ip_address = true
  subnet_id                   = each.value
  vpc_security_group_ids      = [aws_security_group.nat_instance.id]
  iam_instance_profile        = aws_iam_instance_profile.nat_instance.name
  key_name                    = aws_key_pair.agents_key.key_name

  source_dest_check = false

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_size           = 8
    volume_type           = "gp3"
    encrypted             = true
    kms_key_id            = aws_kms_key.ebs.arn
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/userdata.tpl", {
    private_subnet_1_cidr = aws_subnet.agents_private_subnet_1.cidr_block,
    private_subnet_2_cidr = aws_subnet.agents_private_subnet_2.cidr_block,
    log_group_name        = aws_cloudwatch_log_group.nat_instance_logs.name
  })
  user_data_replace_on_change = true

  tags = {
    Name = "${var.project_name}-nat-instance-${each.key}"
  }
}


resource "aws_eip" "nat_instance" {
  for_each = aws_instance.nat_instance
  domain   = "vpc"
  instance = each.value.id

  depends_on = [aws_internet_gateway.agents_igw.id]

  tags = {
    Name = "${var.project_name}-nat-instance-eip-${each.key}"
  }
}

// SSH Config

resource "local_file" "ssh_config" {
  content         = <<-EOF
    # Usage: ssh -F .ssh/config jump-box

    %{for name, inst in aws_instance.jump_box~}
    Host jump-box-${name}
      HostName ${aws_eip.jump_box[name].public_ip}
      User ec2-user
      IdentityFile ${abspath("${path.module}/.ssh/${var.project_name}-key.pem")}
      StrictHostKeyChecking accept-new
      UserKnownHostsFile ${path.module}/.ssh/known_hosts

    Host nat-instance-${name}
      HostName ${aws_eip.nat_instance[name].public_ip}
      User ec2-user
      IdentityFile ${abspath("${path.module}/.ssh/${var.project_name}-key.pem")}
      StrictHostKeyChecking accept-new
      UserKnownHostsFile ${path.module}/.ssh/known_hosts
    %{endfor~}

    EOF
  filename        = "${path.module}/.ssh/config"
  file_permission = "0600"
}
