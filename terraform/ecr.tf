/*
  Elastic Container Registry (ECR) & Bootstrap Automation
  
  Contents:
  - Repositories: Creates dedicated, force-deletable 'api' and 'worker' image repositories.
  - Security & Auditing: Enforces immutable image tags, encrypts images at rest using the shared KMS key, and enables 'scan_on_push' to automatically assess vulnerabilities on every deployment.
  - Lifecycle Policies: Attaches automated cleanup rules to both repositories, retaining only the 20 most recent images to control storage costs.
  - Bootstrap Automation: Uses 'null_resource' and local 'bash' execution to automatically build and push a lightweight dummy 'alpine' image to both repositories upon creation. This prevents ECS task definition failures that occur when referencing empty repositories during initial deployment.
*/

// ECR API Repo

resource "aws_ecr_repository" "api" {
  name                 = "${var.project_name}-api"
  force_delete         = true
  image_tag_mutability = "IMMUTABLE"

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.shared.arn
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
  force_delete         = true
  image_tag_mutability = "IMMUTABLE"

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.shared.arn
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
resource "null_resource" "api_bootstrap_image" {
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<EOF
      aws ecr get-login-password --region ${var.region} --profile ${var.profile} | docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com
      echo "FROM alpine" | docker build -t ${aws_ecr_repository.api.repository_url}:latest -
      docker push ${aws_ecr_repository.api.repository_url}:latest
    EOF
  }
  depends_on = [aws_ecr_repository.api]
}

// Null Resource
// Automatically push an empty image to the Worker repo
resource "null_resource" "worker_bootstrap_image" {
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<EOF
      aws ecr get-login-password --region ${var.region} --profile ${var.profile} | docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com
      echo "FROM alpine" | docker build -t ${aws_ecr_repository.worker.repository_url}:latest -
      docker push ${aws_ecr_repository.worker.repository_url}:latest
    EOF
  }
  depends_on = [aws_ecr_repository.worker]
}
