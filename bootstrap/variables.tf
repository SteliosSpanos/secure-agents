variable "region" {
  type        = string
  description = "AWS region (must match the main stack region)"
  default     = "eu-central-1"
}

variable "project_name" {
  type        = string
  description = "Project name prefix (must match the main stack variable)"
  default     = "secure-agents"
}
