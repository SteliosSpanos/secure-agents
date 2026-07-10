terraform {
  required_version = ">= 1.5, < 2.0"

  backend "s3" {
    bucket       = "secure-agents-terraform-state-502055890709"
    profile      = "terraform-admin"
    key          = "prod/terraform.tfstate"
    region       = "eu-central-1"
    use_lockfile = true
    encrypt      = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  profile = var.profile
  region  = var.region

  default_tags {
    tags = {
      Project = var.project_name
    }
  }
}

provider "aws" {
  alias   = "global"
  profile = var.profile
  region  = "us-east-1"
}
