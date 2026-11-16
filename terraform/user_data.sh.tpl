#!/bin/bash
set -euxo pipefail
dnf install -y docker
systemctl enable --now docker

# Tunggu sampai image tersedia di ECR (pertama kali apply, image belum di-push)
until aws ecr get-login-password --region ${region} | docker login --username AWS --password-stdin ${ecr_registry} \
      && docker pull ${app_image}; do
  echo "Image belum tersedia, coba lagi 30 detik..."; sleep 30
done

docker run -d --name elearning --restart always -p 8080:8080 \
  -e AWS_REGION=${region} \
  -e DB_HOST=${db_host} -e DB_PORT=${db_port} -e DB_NAME=${db_name} \
  -e DB_SECRET_ARN=${db_secret_arn} \
  -e JWT_SECRET_ARN=${jwt_arn} \
  -e REDIS_HOST=${redis_host} \
  -e BUCKET_MATERI=${bucket_materi} -e BUCKET_TUGAS=${bucket_tugas} \
  -e CDN_DOMAIN=${cdn_domain} \
  ${app_image}
