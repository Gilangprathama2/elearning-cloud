variable "project_name" {
  type    = string
  default = "elearning"
}
variable "environment" {
  type    = string
  default = "dev" # dev | prod
}
variable "region" {
  type    = string
  default = "ap-southeast-3" # Jakarta, data tetap di Indonesia (UU PDP)
}
variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}
variable "single_nat" {
  description = "true = 1 NAT Gateway (hemat). false = 1 per AZ (HA, untuk prod)."
  type        = bool
  default     = true
}
variable "acm_certificate_arn" {
  description = "ARN sertifikat ACM (region yang sama dengan ALB) untuk HTTPS. Kosong = HTTP saja (hanya untuk dev)."
  type        = string
  default     = ""
}
variable "cors_origins" {
  description = "Origin yang boleh upload/download langsung ke S3 dari browser. Isi domain aplikasi."
  type        = list(string)
  default     = ["*"]
}

# Database
variable "db_name" {
  type    = string
  default = "elearning"
}
variable "db_instance_class" {
  type    = string
  default = "db.t3.medium"
}
variable "db_multi_az" {
  type    = bool
  default = true
}
variable "db_allocated_storage" {
  type    = number
  default = 50
}

# Cache
variable "redis_node_type" {
  type    = string
  default = "cache.t3.micro"
}

# Compute
variable "app_instance_type" {
  type    = string
  default = "t3.small"
}
variable "asg_min" {
  type    = number
  default = 2
}
variable "asg_max" {
  type    = number
  default = 10
}
variable "asg_desired" {
  type    = number
  default = 2
}
variable "app_image_tag" {
  type    = string
  default = "latest"
}
