output "alb_dns_name" {
  description = "URL aplikasi (arahkan CNAME/Route 53 ke sini)"
  value       = aws_lb.main.dns_name
}
output "cloudfront_domain" { value = aws_cloudfront_distribution.materi.domain_name }
output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "bucket_materi" { value = aws_s3_bucket.this["materi"].id }
output "bucket_tugas" { value = aws_s3_bucket.this["tugas"].id }
output "bucket_backup" { value = aws_s3_bucket.this["backup"].id }
output "rds_endpoint" {
  description = "Hanya bisa diakses dari dalam VPC (subnet app)"
  value       = aws_db_instance.main.address
}
output "db_secret_arn" { value = aws_db_instance.main.master_user_secret[0].secret_arn }
output "private_subnets_db" { value = aws_subnet.db[*].cidr_block }
output "asg_name" { value = aws_autoscaling_group.app.name }
