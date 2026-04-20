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

variable "public_subnet_cidr" {
  type        = string
  default     = "10.0.1.0/24"
  description = "Public subnet CIDR block"
}

variable "private_subnet_1_cidr" {
  type        = string
  default     = "10.0.2.0/24"
  description = "Private subnet 1 CIDR block"
}

variable "private_subnet_2_cidr" {
  type        = string
  default     = "10.0.3.0/24"
  description = "Private subnet 2 CIDR"
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
  default     = "eu.meta.llama3-8b-instruct-v1:0"
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
  type        = string
  default     = "http://localhost:3000"
  description = "Allowed origins for CORS"
}

variable "api_domain" {
  type        = string
  default     = "http://localhost:3000"
  description = "API domain for the URL"
}
