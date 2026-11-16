#!/usr/bin/env bash
# Build & push image aplikasi ke ECR, lalu rolling refresh Auto Scaling Group.
set -euo pipefail
cd "$(dirname "$0")/../terraform"
REPO=$(terraform output -raw ecr_repository_url)
ASG=$(terraform output -raw asg_name)
REGION=${AWS_REGION:-ap-southeast-3}
TAG=${1:-latest}

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${REPO%%/*}"
docker build --platform linux/amd64 -t "$REPO:$TAG" ../app
docker push "$REPO:$TAG"

aws autoscaling start-instance-refresh --auto-scaling-group-name "$ASG" --region "$REGION" \
  --preferences '{"MinHealthyPercentage":50}' || echo "(refresh sudah berjalan / ASG baru dibuat)"
echo "Deploy selesai: $REPO:$TAG"
