# CloudFront untuk materi (video/teks/PDF): cepat di seluruh Indonesia, bucket tetap privat via OAC
resource "aws_cloudfront_origin_access_control" "materi" {
  name                              = "${local.name}-materi-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "materi" {
  enabled         = true
  comment         = "${local.name} materi"
  price_class     = "PriceClass_All"
  http_version    = "http2and3"
  is_ipv6_enabled = true

  origin {
    domain_name              = aws_s3_bucket.this["materi"].bucket_regional_domain_name
    origin_id                = "s3-materi"
    origin_access_control_id = aws_cloudfront_origin_access_control.materi.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-materi"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate { cloudfront_default_certificate = true }
}

data "aws_iam_policy_document" "materi" {
  statement {
    sid       = "AllowCloudFrontOAC"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.this["materi"].arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.materi.arn]
    }
  }
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.this["materi"].arn, "${aws_s3_bucket.this["materi"].arn}/*"]
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

resource "aws_s3_bucket_policy" "materi" {
  bucket     = aws_s3_bucket.this["materi"].id
  policy     = data.aws_iam_policy_document.materi.json
  depends_on = [aws_s3_bucket_public_access_block.this]
}
