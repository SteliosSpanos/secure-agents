terraform {
  required_version = ">= 1.5, < 2.0"

  /*
  backend "s3" {
    bucket         = "agents-terraform-state-487322974754"
    key            = "terraform.tfstate"
    region         = "eu-central-1"
    dynamodb_table = "agents-terraform-locks"
    encrypt        = true
  }
  */

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }

    local = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
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
