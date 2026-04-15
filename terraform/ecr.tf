/*
    The ECR repos for the API and the Worker
*/

// ECR API Repo

resource "aws_ecr_repository" "api" {
  name                 = "${var.project_name}-api"
  image_tag_mutability = "MUTABLE"

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.agents.arn
  }

  image_scanning_configuration {
    scan_on_push = true // Scan for vulnerabilities on every push
  }

  tags = {
    Name = "${var.project_name}-api-repo"
  }
}

// API Repo Lifecycle

resource "aws_ecr_lifecycle_policy" "api_policy" {
  repository = aws_ecr_repository.api.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 20 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = {
        type = "expire"
      }
    }]
  })
}




// ECR Worker Repo

resource "aws_ecr_repository" "worker" {
  name                 = "${var.project_name}-worker"
  image_tag_mutability = "MUTABLE"

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.agents.arn
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "${var.project_name}-worker-repo"
  }
}

// Worker Repo Lifecycle

resource "aws_ecr_lifecycle_policy" "worker_policy" {
  repository = aws_ecr_repository.worker.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 20 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = {
        type = "expire"
      }
    }]
  })
}

// Null Resource
// Automatically push an empty image to the API repo

resource "null_resource" "worker_bootstrap_image" {
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<EOF
      aws ecr get-login-password --region ${var.region} | docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com
      echo "FROM scratch" > Dockerfile.dummy
      docker build -t ${aws_ecr_repository.api.repository_url}:${var.image_tag} -f Dockerfile.dummy .
      docker push ${aws_ecr_repository.api.repository_url}:${var.image_tag}
      rm Dockerfile.dummy
    EOF
  }
  depends_on = [aws_ecr_repository.api]
}

// Null Resource
// Automatically push an empty image to the Worker repo

resource "null_resource" "api_bootstrap_image" {
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<EOF
      aws ecr get-login-password --region ${var.region} | docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com
      echo "FROM scratch" > Dockerfile.dummy
      docker build -t ${aws_ecr_repository.worker.repository_url}:${var.image_tag} -f Dockerfile.dummy .
      docker push ${aws_ecr_repository.worker.repository_url}:${var.image_tag}
      rm Dockerfile.dummy
    EOF
  }
  depends_on = [aws_ecr_repository.worker]
}
