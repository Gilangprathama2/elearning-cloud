locals {
  buckets = {
    materi = { sse = "AES256", transition_days = 0, storage_class = "" }       # materi dosen, disajikan via CloudFront (OAC)
    tugas  = { sse = "aws:kms", transition_days = 90, storage_class = "STANDARD_IA" } # tugas mahasiswa, privat
    backup = { sse = "aws:kms", transition_days = 30, storage_class = "GLACIER" }     # arsip semester lama
  }
}

resource "aws_kms_key" "main" {
  description             = "${local.name} - enkripsi RDS, S3 (tugas/backup), Secrets"
  enable_key_rotation     = true
  deletion_window_in_days = 14
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.main.key_id
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets
  bucket   = "${local.name}-${each.key}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    bucket_key_enabled = local.buckets[each.key].sse == "aws:kms"
    apply_server_side_encryption_by_default {
      sse_algorithm     = local.buckets[each.key].sse
      kms_master_key_id = local.buckets[each.key].sse == "aws:kms" ? aws_kms_key.main.arn : null
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id

  rule {
    id     = "default"
    status = "Enabled"
    filter {}

    abort_incomplete_multipart_upload { days_after_initiation = 7 } # upload video besar yang gagal

    noncurrent_version_expiration { noncurrent_days = 180 }

    dynamic "transition" {
      for_each = local.buckets[each.key].transition_days > 0 ? [1] : []
      content {
        days          = local.buckets[each.key].transition_days
        storage_class = local.buckets[each.key].storage_class
      }
    }
  }
  depends_on = [aws_s3_bucket_versioning.this]
}

# CORS: browser upload langsung ke S3 (presigned URL) & streaming video
resource "aws_s3_bucket_cors_configuration" "browser" {
  for_each = { for k, v in aws_s3_bucket.this : k => v if k != "backup" }
  bucket   = each.value.id
  cors_rule {
    allowed_methods = ["GET", "PUT", "POST", "HEAD"]
    allowed_origins = var.cors_origins
    allowed_headers = ["*"]
    expose_headers  = ["ETag"] # dibutuhkan multipart upload
    max_age_seconds = 3000
  }
}

# Wajib TLS untuk bucket tugas & backup (policy materi ada di cdn.tf)
data "aws_iam_policy_document" "tls_only" {
  for_each = { for k, v in aws_s3_bucket.this : k => v if k != "materi" }
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [each.value.arn, "${each.value.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tls_only" {
  for_each = data.aws_iam_policy_document.tls_only
  bucket   = aws_s3_bucket.this[each.key].id
  policy   = each.value.json
  depends_on = [aws_s3_bucket_public_access_block.this]
}
