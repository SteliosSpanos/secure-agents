variable "profile" {
  type        = string
  default     = null
  description = "AWS CLI profile"
}

variable "region" {
  type        = string
  default     = "eu-central-1"
  description = "AWS region"
}

variable "email" {
  type        = string
  default     = null
  description = "Email for alerts"
}

variable "project_name" {
  type        = string
  default     = "agents"
  description = "Project name for resource naming"
}

variable "vpc_cidr" {
  type        = string
  default     = "10.0.0.0/16"
  description = "VPC CIDR block"
}

variable "private_subnet_1_cidr" {
  type        = string
  default     = "10.0.3.0/24"
  description = "Private subnet 1 CIDR block"
}

variable "private_subnet_2_cidr" {
  type        = string
  default     = "10.0.4.0/24"
  description = "Private subnet 2 CIDR"
}

variable "public_subnet_1_cidr" {
  type        = string
  default     = "10.0.1.0/24"
  description = "Public subnet 1 CIDR"
}

variable "public_subnet_2_cidr" {
  type        = string
  default     = "10.0.2.0/24"
  description = "Public subnet 2 CIDR"
}

variable "sqs_retention_days" {
  type        = number
  default     = 4
  description = "How long to keep a message in the work queue"
}

variable "sqs_dlq_retention_days" {
  type        = number
  default     = 14
  description = "How long to keep failed messages in the DLQ"
}

variable "bedrock_model_id" {
  type        = string
  default     = "eu.anthropic.claude-3-haiku-20240307-v1:0"
  description = "Bedrock foundation model ID"
}

variable "image_tag" {
  type        = string
  default     = "latest"
  description = "The tag of the image to deploy"
}

variable "log_retention_days" {
  type        = number
  default     = 30
  description = "How long to keep CloudWatch logs"
}

variable "allowed_origins" {
  type = list(string)
  default = [
    "https://d90xnc0ve8xm0.cloudfront.net"
  ]
  description = "Allowed origins for CORS. Local development must override this explicitly (e.g. via terraform.tfvars) to include http://localhost:3000 - it is not a shipped default. Also drives the S3 bucket CORS rule at s3.tf:57, not just the API's ALLOWED_ORIGINS env var."
}

variable "public_key_path" {
  type        = string
  default     = ".ssh/agents-key.pem.pub"
  description = "Path to the public key file"
}

variable "instance_types" {
  type = object({
    jump_box     = string
    nat_instance = string
  })
  default = {
    jump_box     = "t3.micro"
    nat_instance = "t3.micro"
  }
  description = "EC2 instance types for each instance"
}

variable "admin_principal_arns" {
  type        = list(string)
  default     = []
  description = "Stable IAM user/role ARNs exempted from the DynamoDB VPC-endpoint-restriction Deny (the 'prevent lockout' escape hatch)"

  validation {
    condition     = alltrue([for a in var.admin_principal_arns : startswith(a, "arn:aws:iam::")])
    error_message = "admin_principal_arns must contain only stable arn:aws:iam:: user/role ARNs, not arn:aws:sts:: assumed-role session ARNs."
  }
}
