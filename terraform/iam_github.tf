/*
    Configuration of Github Actions Role for executing the pipeline
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
    condition { // Only allow your specific repository to assume this role
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:SteliosSpanos/secure-agents:*"]
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
      "ecr:UpdateService",
      "ecr:DescribeServices"
    ]
    resources = [
      aws_ecs_service.api_service.id,
      aws_ecs_service.worker_service.id
    ]
  }
}

resource "aws_iam_role_policy" "github_actions_policy" {
  name   = "GithubActionsPolicy"
  role   = aws_iam_role.github_actions_role.id
  policy = data.aws_iam_policy_document.github_actions_permissions.json
}
