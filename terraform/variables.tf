variable "profile" {
  type        = string
  description = "AWS CLI profile"
}

variable "region" {
  type        = string
  description = "AWS region"
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
