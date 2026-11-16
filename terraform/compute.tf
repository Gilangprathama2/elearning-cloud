# ---------- ECR (image aplikasi) ----------
resource "aws_ecr_repository" "app" {
  name                 = "${local.name}-app"
  image_tag_mutability = "MUTABLE"
  force_delete         = var.environment != "prod"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }
}

# ---------- IAM Role untuk server aplikasi (least privilege) ----------
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name_prefix        = "${local.name}-app-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore" # akses admin tanpa SSH
}
resource "aws_iam_role_policy_attachment" "ecr_read" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}
resource "aws_iam_role_policy_attachment" "cw_agent" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

data "aws_iam_policy_document" "app" {
  statement {
    sid     = "S3Objects"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
    resources = [
      "${aws_s3_bucket.this["materi"].arn}/*",
      "${aws_s3_bucket.this["tugas"].arn}/*",
    ]
  }
  statement {
    sid       = "S3List"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.this["materi"].arn, aws_s3_bucket.this["tugas"].arn]
  }
  statement {
    sid       = "Kms"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [aws_kms_key.main.arn]
  }
  statement {
    sid     = "Secrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_db_instance.main.master_user_secret[0].secret_arn,
      aws_secretsmanager_secret.jwt.arn,
    ]
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "app-access"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app.json
}

resource "aws_iam_instance_profile" "app" {
  name_prefix = "${local.name}-app-"
  role        = aws_iam_role.app.name
}

# ---------- Launch Template + Auto Scaling ----------
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_launch_template" "app" {
  name_prefix   = "${local.name}-app-"
  image_id      = data.aws_ssm_parameter.al2023.value
  instance_type = var.app_instance_type

  iam_instance_profile { arn = aws_iam_instance_profile.app.arn }
  vpc_security_group_ids = [aws_security_group.app.id]

  metadata_options {
    http_tokens                 = "required" # IMDSv2
    http_put_response_hop_limit = 2          # container perlu hop 2
  }
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size = 20
      volume_type = "gp3"
      encrypted   = true
      kms_key_id  = aws_kms_key.main.arn
    }
  }

  user_data = base64encode(templatefile("${path.module}/user_data.sh.tpl", {
    region        = var.region
    ecr_registry  = split("/", aws_ecr_repository.app.repository_url)[0]
    app_image     = "${aws_ecr_repository.app.repository_url}:${var.app_image_tag}"
    db_host       = aws_db_instance.main.address
    db_port       = aws_db_instance.main.port
    db_name       = var.db_name
    db_secret_arn = aws_db_instance.main.master_user_secret[0].secret_arn
    jwt_arn       = aws_secretsmanager_secret.jwt.arn
    redis_host    = aws_elasticache_replication_group.redis.primary_endpoint_address
    bucket_materi = aws_s3_bucket.this["materi"].id
    bucket_tugas  = aws_s3_bucket.this["tugas"].id
    cdn_domain    = aws_cloudfront_distribution.materi.domain_name
  }))

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${local.name}-app" }
  }
  lifecycle { create_before_destroy = true }
}

resource "aws_autoscaling_group" "app" {
  name_prefix         = "${local.name}-app-"
  min_size            = var.asg_min
  max_size            = var.asg_max
  desired_capacity    = var.asg_desired
  vpc_zone_identifier = aws_subnet.app[*].id
  target_group_arns   = [aws_lb_target_group.app.arn]

  health_check_type         = "ELB"
  health_check_grace_period = 300

  launch_template {
    id      = aws_launch_template.app.id
    version = aws_launch_template.app.latest_version
  }

  instance_refresh {
    strategy = "Rolling"
    preferences { min_healthy_percentage = 50 }
  }
  lifecycle { create_before_destroy = true }
}

# Scale berdasarkan CPU dan jumlah request per instance (puncak: deadline tugas / UTS / UAS)
resource "aws_autoscaling_policy" "cpu" {
  name                   = "${local.name}-cpu"
  autoscaling_group_name = aws_autoscaling_group.app.name
  policy_type            = "TargetTrackingScaling"
  target_tracking_configuration {
    predefined_metric_specification { predefined_metric_type = "ASGAverageCPUUtilization" }
    target_value = 60
  }
}

resource "aws_autoscaling_policy" "requests" {
  name                   = "${local.name}-requests"
  autoscaling_group_name = aws_autoscaling_group.app.name
  policy_type            = "TargetTrackingScaling"
  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.main.arn_suffix}/${aws_lb_target_group.app.arn_suffix}"
    }
    target_value = 500
  }
}
