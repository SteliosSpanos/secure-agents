/*
  GitHub Actions CI/CD Pipeline Configuration (OIDC Integration)
  
  Contents:
  - OIDC Identity Provider: Establishes a keyless, secure trust relationship between AWS and GitHub Actions using GitHub's TLS thumbprint.
  - Strict Trust Policy: Restricts the 'sts:AssumeRoleWithWebIdentity' action exclusively to the 'SteliosSpanos/secure-agents' repository and specifically the 'main' branch.
  - Least-Privilege CI/CD Permissions: 
    * ECR: Grants scoped access to upload image layers specifically to the 'api' and 'worker' repositories.
    * ECS: Allows registering new task definitions and updating the designated ECS services.
    * IAM PassRole: Safely permits passing the API/Worker execution and task roles strictly to 'ecs-tasks.amazonaws.com'.
    * SSM Parameter Store: Scoped access to read/write deployment variables under the '/agents/*' path.
*/

// Fetch the TLS certificate for Github's OIDC server

data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com"
}

// Create the OIDC provider in AWS
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]
}

// IAM Role

data "aws_iam_policy_document" "github_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition { // Only allow our specific repository and main branch to assume this role 
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:SteliosSpanos/secure-agents:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_actions_role" {
  name               = "GithubActionsRole"
  assume_role_policy = data.aws_iam_policy_document.github_assume_role.json
}

// Permissions

data "aws_iam_policy_document" "github_actions_permissions" {
  statement {
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload"
    ]
    resources = [
      aws_ecr_repository.api.arn,
      aws_ecr_repository.worker.arn
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "ecs:UpdateService",
      "ecs:DescribeServices"
    ]
    resources = [
      aws_ecs_service.api_service.id,
      aws_ecs_service.worker_service.id
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "ecs:RegisterTaskDefinition",
      "ecs:DescribeTaskDefinition"
    ]
    resources = ["*"] // ECS doesn't support resource-level scoping for these two actions 
  }

  statement {
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.api_task_role.arn,
      aws_iam_role.agent_task_role.arn,
      aws_iam_role.ecs_execution_role.arn
    ]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    effect  = "Allow"
    actions = ["ssm:PutParameter", "ssm:GetParameter"]
    resources = [
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/agents/*"
    ]
  }
}

resource "aws_iam_role_policy" "github_actions_policy" {
  name   = "GithubActionsPolicy"
  role   = aws_iam_role.github_actions_role.id
  policy = data.aws_iam_policy_document.github_actions_permissions.json
}
