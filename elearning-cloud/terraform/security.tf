# ---------- Security Group berlapis: Internet -> ALB -> App -> DB/Redis ----------
resource "aws_security_group" "alb" {
  name_prefix = "${local.name}-alb-"
  description = "ALB: HTTP/HTTPS dari internet"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "app" {
  name_prefix = "${local.name}-app-"
  description = "App server: hanya menerima dari ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"] # keluar via NAT / VPC endpoint
  }
  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "db" {
  name_prefix = "${local.name}-db-"
  description = "RDS: hanya dari SG App"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
  # tidak ada egress rule -> DB tidak bisa memulai koneksi keluar
  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "redis" {
  name_prefix = "${local.name}-redis-"
  description = "Redis: hanya dari SG App"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
  lifecycle { create_before_destroy = true }
}

# ---------- Network ACL untuk subnet DB (lapisan tambahan) ----------
resource "aws_network_acl" "db" {
  vpc_id     = aws_vpc.main.id
  subnet_ids = aws_subnet.db[*].id
  tags       = { Name = "${local.name}-nacl-db" }
}

resource "aws_network_acl_rule" "db_in_postgres" {
  count          = 2
  network_acl_id = aws_network_acl.db.id
  rule_number    = 100 + count.index
  egress         = false
  protocol       = "tcp"
  rule_action    = "allow"
  cidr_block     = local.app_cidrs[count.index]
  from_port      = 5432
  to_port        = 5432
}

resource "aws_network_acl_rule" "db_in_redis" {
  count          = 2
  network_acl_id = aws_network_acl.db.id
  rule_number    = 110 + count.index
  egress         = false
  protocol       = "tcp"
  rule_action    = "allow"
  cidr_block     = local.app_cidrs[count.index]
  from_port      = 6379
  to_port        = 6379
}

# Replikasi Multi-AZ antar subnet DB
resource "aws_network_acl_rule" "db_in_internal" {
  count          = 2
  network_acl_id = aws_network_acl.db.id
  rule_number    = 120 + count.index
  egress         = false
  protocol       = "-1"
  rule_action    = "allow"
  cidr_block     = local.db_cidrs[count.index]
}

resource "aws_network_acl_rule" "db_out_app" {
  count          = 2
  network_acl_id = aws_network_acl.db.id
  rule_number    = 100 + count.index
  egress         = true
  protocol       = "tcp"
  rule_action    = "allow"
  cidr_block     = local.app_cidrs[count.index]
  from_port      = 1024
  to_port        = 65535
}

resource "aws_network_acl_rule" "db_out_internal" {
  count          = 2
  network_acl_id = aws_network_acl.db.id
  rule_number    = 120 + count.index
  egress         = true
  protocol       = "-1"
  rule_action    = "allow"
  cidr_block     = local.db_cidrs[count.index]
}
