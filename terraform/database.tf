# ---------- RDS PostgreSQL di private DB subnet ----------
resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.db[*].id
}

resource "aws_db_parameter_group" "pg" {
  name_prefix = "${local.name}-pg16-"
  family      = "postgres16"
  parameter {
    name  = "rds.force_ssl" # tolak koneksi tanpa TLS
    value = "1"
  }
  lifecycle { create_before_destroy = true }
}

resource "aws_db_instance" "main" {
  identifier     = "${local.name}-db"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  db_name  = var.db_name
  username = "elearning_admin"
  # Password dibuat & dirotasi RDS, disimpan di Secrets Manager (tidak pernah ada di code/state)
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.main.arn

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_allocated_storage * 4
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.main.arn

  multi_az               = var.db_multi_az
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.pg.name
  publicly_accessible    = false # <-- inti proteksi database

  iam_database_authentication_enabled = true
  backup_retention_period             = 7
  backup_window                       = "17:00-18:00" # 00:00-01:00 WIB
  maintenance_window                  = "sun:18:00-sun:19:00"
  copy_tags_to_snapshot               = true
  auto_minor_version_upgrade          = true
  enabled_cloudwatch_logs_exports     = ["postgresql", "upgrade"]

  deletion_protection       = var.environment == "prod"
  skip_final_snapshot       = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "${local.name}-final" : null
}

# ---------- ElastiCache Redis (sesi & cache) ----------
resource "aws_elasticache_subnet_group" "main" {
  name       = "${local.name}-redis"
  subnet_ids = aws_subnet.db[*].id
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "${local.name}-redis"
  description                = "Cache & sesi e-learning"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.redis_node_type
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  multi_az_enabled           = true
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  kms_key_id                 = aws_kms_key.main.arn
}

# ---------- Secret untuk JWT aplikasi ----------
resource "random_password" "jwt" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "jwt" {
  name_prefix = "${local.name}-jwt-"
  kms_key_id  = aws_kms_key.main.arn
}

resource "aws_secretsmanager_secret_version" "jwt" {
  secret_id     = aws_secretsmanager_secret.jwt.id
  secret_string = random_password.jwt.result
}
